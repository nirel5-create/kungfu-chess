"""Registry of live games: which exist, who sits in which seat, and what
happens to a game once it ends.

This is `Server_Design.md`'s Game Allocator boundary, at the smallest scale
that answers "who decides which game you sit in". Before this module, the
server built exactly ONE GameSession at startup and kept it forever: once
that session's king fell, every later arrival got a permanently-finished
game and closed immediately. This module is the fix -- a server holds MANY
games, each with its own lifecycle -- but it deliberately does not decide
WHICH game a new arrival joins. That is policy, kept in server.py's
_find_or_create_game on purpose, so Play (slide 5) and Room (slide 6) can
later replace only that one function, with no change here.

What this module owns: which games exist, who sits in which seat of which
game, and what happens to a game after it ends (a lingering period, then
removal).
What it does NOT own: how a player is matched to a game (policy, kept out on
purpose), sockets, broadcasting, rating arithmetic, or the passage of real
time -- advance(ms) takes an explicit ms, exactly as GameSession.advance(ms)
already does, so behaviour is deterministic and testable without a real
clock.

Why publish lifecycle events instead of writing to a database: this module
does not know what a rating is. It announces GAME_START/GAME_END and moves
on; whoever cares subscribes to the Bus. That is the same write-behind split
Server_Design.md argues for when Postgres is down, and it is what lets ELO
be added later as a bus subscriber, with no change to this file.
"""

import uuid

from common import topics

GAME_END_LINGER_MS = 3000  # how long a finished game stays before removal

# GameSession exposes no way to read a game's Config: it holds a private
# GameEngine, which itself holds a private Config, and neither has a public
# accessor (checked in engine/game.py and common/net.py before writing this
# -- there is nothing to reach). So the king's token cannot be read from a
# session, and is instead taken as a constructor argument here, defaulting
# to the same value Config itself defaults to.
_DEFAULT_KING_TYPE = "K"

_SEAT_COLORS = ("w", "b")


class AlreadyConnectedError(Exception):
    """Raised by join() when `username` already has a LIVE connection to
    `game_id` -- a second, simultaneous connection under the same name,
    not a reconnect. This used to be handled by silently seating the
    second connection as "viewer": that stopped the second window from
    controlling the first one's pieces, but gave the player at that second
    window no explanation -- they would just find they could not move
    anything and have to guess why. Raising a named exception lets the
    caller (server.py) tell them instead: a refusal the player can read
    beats a silent demotion they must deduce."""


class _Game:  # pylint: disable=too-few-public-methods
    # A plain mutable data holder, private to this module -- callers only
    # ever see a game_id, never a _Game, so it needs no public API of its
    # own; GameRegistry reads and writes its fields directly.
    """One registry entry: a session plus the seats and connection state
    around it. Private to this module -- callers only ever see a game_id."""

    def __init__(self, session):
        self.session = session
        self.seats = {}          # username -> "w" | "b" | "viewer"
        self.connected = set()   # usernames currently connected
        self.ended = False       # has GAME_END already been published?
        self.linger_ms = 0       # ms accumulated since ended became True


class GameRegistry:
    """Owns every live game and its seats. No asyncio, no sockets -- the
    server is the only thing that ticks it and reads what it returns."""

    def __init__(self, make_session, bus=None, king_type=_DEFAULT_KING_TYPE):
        """make_session -- zero-argument callable returning a fresh
        GameSession. Injected, not imported: this module must not know how
        a board or engine is built, which is what lets a test hand it a
        tiny 1x3 board.
        bus -- an optional common.bus.Bus. When given, GAME_START and
        GAME_END are published on it; when None, nothing is published and
        everything else about the registry is unchanged.
        king_type -- the token (e.g. "K") that marks a king in a snapshot's
        pieces; see the module-level comment on why this cannot be read
        from a session itself."""
        self._make_session = make_session
        self._bus = bus
        self._king_type = king_type
        self._games = {}  # game_id -> _Game

    def create(self, game_id=None):
        """-> the new game's id. Generates a short unique id when `game_id`
        is None; a given id is used as-is, which is what Room (slide 6)
        will need later, since a room's id is its own name. Raises
        ValueError if `game_id` already names a live game -- silently
        replacing it would drop whatever game was inside."""
        if game_id is None:
            game_id = self._generate_id()
        elif game_id in self._games:
            raise ValueError(f"a game with id {game_id!r} already exists")
        self._games[game_id] = _Game(self._make_session())
        self._publish(topics.GAME_START, {"game_id": game_id})
        return game_id

    def _generate_id(self):
        while True:
            game_id = uuid.uuid4().hex[:8]
            if game_id not in self._games:
                return game_id

    def join(self, game_id, username):
        """-> the color seated for `username` in `game_id`: "w", "b", or
        "viewer". Raises KeyError for an unknown game_id.

        A username that already has a seat AND IS NOT CURRENTLY CONNECTED
        gets that same seat back -- this is what makes reconnecting work,
        since leave() below does not erase the seat. Only the SEAT is made
        stable here; a *timed* reconnect window (a grace period before the
        seat is forfeited) is a later step. This step deliberately only
        guarantees the seat does not silently vanish on disconnect, nothing
        about how long it waits.

        A username that already has a seat AND IS CURRENTLY CONNECTED is a
        second, simultaneous connection under the same name, not a
        reconnect -- "I am coming back" and "I am already connected
        elsewhere" look identical if only `seats` is consulted, but
        `connected` (already tracked, for exactly this) tells them apart.
        Raises AlreadyConnectedError for that case rather than seating the
        second connection as "viewer": the earlier "viewer" behaviour did
        stop the second window from controlling the first one's pieces, but
        left the player with nothing but an unresponsive board to explain
        why. The original seat is left untouched either way -- only how
        the second connection is told about it changes. (This is scoped to
        exactly that case -- `connected` records USERNAMES, not a count of
        live connections per username, so if the original connection then
        leaves while a rejected second attempt is somehow still retrying, a
        later join looks like a fresh reconnect again. Closing that gap
        needs counting connections, not just tracking who has ever joined;
        not needed for the bug this fixes.)

        Otherwise, the first of "w"/"b" not already held by some username
        in this game is assigned; if both are held, the seat is "viewer"."""
        game = self._games[game_id]
        if username in game.seats:
            if username in game.connected:
                raise AlreadyConnectedError(username)
            game.connected.add(username)
            return game.seats[username]
        color = self._next_open_seat(game)
        game.seats[username] = color
        game.connected.add(username)
        return color

    @staticmethod
    def _next_open_seat(game):
        held = set(game.seats.values())
        for color in _SEAT_COLORS:
            if color not in held:
                return color
        return "viewer"

    def leave(self, game_id, username):
        """Mark `username` as disconnected from `game_id`. Does not free
        the seat -- see join(). A no-op for an unknown game or an unknown
        username: a disconnect can arrive after a game has already been
        removed, and that is normal, not exceptional."""
        game = self._games.get(game_id)
        if game is not None:
            game.connected.discard(username)

    def color_of(self, game_id, username):
        """-> the seat held by `username` in `game_id`, or None if that
        username has no seat there or the game does not exist."""
        game = self._games.get(game_id)
        if game is None:
            return None
        return game.seats.get(username)

    def session(self, game_id):
        """-> the GameSession for `game_id`, or None if it does not exist
        (never created, or removed after its linger period elapsed)."""
        game = self._games.get(game_id)
        return game.session if game is not None else None

    def game_ids(self):
        """-> a tuple of every currently-live game id."""
        return tuple(self._games)

    def advance(self, ms):
        """Tick every live game's session by `ms`, publish GAME_END exactly
        once for each game that just became game_over, and remove any game
        whose linger period has run past GAME_END_LINGER_MS.

        The linger period is counted from the same call in which a game
        becomes game_over -- this call's `ms` already counts toward it, not
        just later calls' -- so behaviour does not depend on how finely the
        caller chops time into advance() calls."""
        for game_id, game in list(self._games.items()):
            game.session.advance(ms)
            if game.session.game_over and not game.ended:
                game.ended = True
                self._publish(topics.GAME_END, {
                    "game_id": game_id,
                    "winner": self._winner_of(game.session),
                    "seats": dict(game.seats),
                })
            if game.ended:
                game.linger_ms += ms
                if game.linger_ms >= GAME_END_LINGER_MS:
                    del self._games[game_id]

    def _winner_of(self, session):
        """The color whose king is still on the board, or None if neither
        color's king is present, or both are (can't happen with one king
        per side, but a custom Config is free to allow it)."""
        kings = {p.color for p in session.snapshot().pieces
                 if p.kind == self._king_type}
        if len(kings) == 1:
            return next(iter(kings))
        return None

    def _publish(self, topic, payload):
        if self._bus is not None:
            self._bus.publish(topic, payload)
