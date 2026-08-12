"""GameRegistry: which games exist, who sits in which seat, and what
happens to a game once it ends.

What this module owns: which games exist, who sits in which seat of
which game, and what happens to a game after it ends (a lingering
period, then removal). What it does NOT own: how a player is matched to
a game, sockets, broadcasting, or rating arithmetic.

Two decisions kept deliberately outside this module: WHICH game a new
arrival joins is policy, left to server.py's _find_or_create_game so
Play and Room can each replace just that function; and a game's
lifecycle (GAME_START/GAME_END) is announced on the Bus rather than
acted on directly, since this module does not know what a rating is --
letting ELO be added later as a subscriber, with no change here."""

import uuid

from common import topics
from common.registry.game import AlreadyConnectedError, _Game

GAME_END_LINGER_MS = 3000  # how long a finished game stays before removal
DISCONNECT_GRACE_MS = 20000  # auto-resign 20s after a disconnect

# GameSession exposes no way to read a game's Config: it holds a private
# GameEngine, which itself holds a private Config, and neither has a public
# accessor (checked in engine/game.py and common/net.py before writing this
# -- there is nothing to reach). So the king's token cannot be read from a
# session, and is instead taken as a constructor argument here, defaulting
# to the same value Config itself defaults to.
_DEFAULT_KING_TYPE = "K"

_SEAT_COLORS = ("w", "b")


class GameRegistry:
    """Owns every live game and its seats. No asyncio, no sockets -- the
    server is the only thing that ticks it and reads what it returns."""

    def __init__(self, make_session, bus=None, king_type=_DEFAULT_KING_TYPE):
        """make_session -- zero-argument callable returning a fresh
        GameSession, injected so this module need not know how a board or
        engine is built (a test can hand it a tiny 1x3 board). bus --
        optional common.bus.Bus; GAME_START/GAME_END publish on it when
        given. king_type -- the token marking a king in a snapshot's pieces."""
        self._make_session = make_session
        self._bus = bus
        self._king_type = king_type
        self._games = {}  # game_id -> _Game

    def create(self, game_id=None):
        """-> the new game's id. Generates a short unique id when `game_id`
        is None; a given id is used as-is, which is what Room needs, since
        a room's id is its own name. Raises ValueError if `game_id` already
        names a live game -- silently replacing it would drop whatever
        game was inside."""
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
        """-> the color seated for `username`: the first open "w"/"b" seat,
        or "viewer" once both are held; a disconnected seat holder gets it
        back with its countdown cleared. Raises KeyError for an unknown
        game_id, and AlreadyConnectedError if already connected -- a second
        window, not a reconnect -- rather than silently doubling as a viewer."""
        game = self._games[game_id]
        if username in game.seats:
            if username in game.connected:
                raise AlreadyConnectedError(username)
            game.connected.add(username)
            game.away_ms.pop(username, None)
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
        """Mark `username` as disconnected from `game_id`, without freeing
        the seat. A no-op for an unknown game or username. If `username`
        holds "w" or "b", also starts their disconnect countdown at 0; a
        viewer leaving starts nothing -- walking away is not a forfeit."""
        game = self._games.get(game_id)
        if game is not None:
            game.connected.discard(username)
            if game.seats.get(username) in _SEAT_COLORS:
                game.away_ms[username] = 0

    def color_of(self, game_id, username):
        """-> the seat held by `username` in `game_id`, or None if that
        username has no seat there or the game does not exist."""
        game = self._games.get(game_id)
        if game is None:
            return None
        return game.seats.get(username)

    def seats(self, game_id):
        """-> {username: color} for every seat taken in `game_id`
        (including viewers), or {} for an unknown game_id. The same shape
        GAME_END's payload carries, but for a LIVE game: lets the server
        show each seat's display name as it is taken, not only once the
        game ends."""
        game = self._games.get(game_id)
        if game is None:
            return {}
        return dict(game.seats)

    def session(self, game_id):
        """-> the GameSession for `game_id`, or None if it does not exist
        (never created, or removed after its linger period elapsed)."""
        game = self._games.get(game_id)
        return game.session if game is not None else None

    def game_of(self, username):
        """-> the game_id of a live (not yet ended) game `username`
        already holds a seat in, or None. A username holds a seat in at
        most one live game at a time -- join() refuses a second,
        still-connected attempt, and a seat once given never moves to a
        different username -- so at most one game_id can ever match."""
        for game_id, game in self._games.items():
            if username in game.seats and not game.session.game_over:
                return game_id
        return None

    def game_ids(self):
        """-> a tuple of every currently-live game id."""
        return tuple(self._games)

    def countdown_ms(self, game_id):
        """-> {username: ms remaining before auto-resign}, for every
        seated player currently away in `game_id`. Empty when nobody is
        away, and empty -- not an error -- for an unknown game_id too.
        The server broadcasts this as whole seconds, not milliseconds,
        so the opponent can see the count on screen."""
        game = self._games.get(game_id)
        if game is None:
            return {}
        return {username: max(0, DISCONNECT_GRACE_MS - away)
                for username, away in game.away_ms.items()}

    def has_connected_players(self, game_id):
        """-> whether any username is currently connected to `game_id`
        (False for an unknown game_id too). Lets server.py check this
        without reaching into GameRegistry's internals -- without it, a
        stranger could be handed an abandoned game (seats never freed
        but nobody connected), waiting for an opponent already gone."""
        game = self._games.get(game_id)
        if game is None:
            return False
        return bool(game.connected)

    def both_seated(self, game_id):
        """-> whether BOTH "w" and "b" are currently held in `game_id`
        (False for an unknown game_id too). Without this, a lone player
        could capture the opponent's undefended king for a free,
        repeatable win. Seats are sticky, so once True this stays True
        even after a later disconnect -- only the countdown governs that."""
        game = self._games.get(game_id)
        if game is None:
            return False
        colors = set(game.seats.values())
        return "w" in colors and "b" in colors

    def advance(self, ms):
        """Tick every live game's session by `ms`, publish GAME_END once
        for each game that just ended (king capture or auto-resign), and
        remove any game whose linger period, counted from the call it
        ended in, has passed GAME_END_LINGER_MS. Auto-resign runs only
        via `elif` when not already ended, so one call never double-publishes."""
        for game_id, game in list(self._games.items()):
            game.session.advance(ms)
            if game.session.game_over and not game.ended:
                game.ended = True
                self._publish(topics.GAME_END, {
                    "game_id": game_id,
                    "winner": self._winner_of(game.session),
                    "seats": dict(game.seats),
                })
            elif not game.ended:
                self._advance_countdowns(game_id, game, ms)
            if game.ended:
                game.linger_ms += ms
                if game.linger_ms >= GAME_END_LINGER_MS:
                    del self._games[game_id]

    def _advance_countdowns(self, game_id, game, ms):
        """Add `ms` to every seated player's disconnect countdown and
        auto-resign whoever reaches DISCONNECT_GRACE_MS. Winner is the
        seated color that did NOT time out; if both did, or a color was
        never seated (excluded, not "remaining"), the winner is None.
        Ends the game the same way a king capture does, one GAME_END."""
        if not game.away_ms:
            return
        expired = set()
        for username in game.away_ms:
            game.away_ms[username] += ms
            if game.away_ms[username] >= DISCONNECT_GRACE_MS:
                expired.add(username)
        if not expired:
            return
        seated_colors = [color for color in _SEAT_COLORS
                          if self._username_at(game, color) is not None]
        expired_colors = {color for color in seated_colors
                           if self._username_at(game, color) in expired}
        remaining_colors = [c for c in seated_colors if c not in expired_colors]
        winner = remaining_colors[0] if len(remaining_colors) == 1 else None
        game.session.force_game_over()  # no king was captured, so the
        #   (frozen) engine has no idea this game just ended.
        game.ended = True
        self._publish(topics.GAME_END, {
            "game_id": game_id,
            "winner": winner,
            "seats": dict(game.seats),
        })

    @staticmethod
    def _username_at(game, color):
        """-> the username seated at `color` in `game`, or None if that
        seat has never been taken. A small lookup helper for
        _advance_countdowns, which needs to go from a color to "is THIS
        color's occupant currently expired" -- the reverse direction of
        the more common username -> color lookups elsewhere."""
        for username, seat_color in game.seats.items():
            if seat_color == color:
                return username
        return None

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
