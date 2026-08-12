"""The two small pieces GameRegistry (registry.py) builds itself out of: the
error it raises on a duplicate live connection, and the plain per-game data
holder it keeps one of per live game.
"""


class AlreadyConnectedError(Exception):
    """Raised by GameRegistry.join() when `username` already has a LIVE
    connection to a game -- a second, simultaneous connection under the
    same name, not a reconnect. Raising a named exception lets the
    caller (server.py) tell the player why, rather than silently seating
    them as an unresponsive "viewer" with nothing to explain it."""


class _Game:  # pylint: disable=too-few-public-methods
    # A plain mutable data holder, private to this package -- callers only
    # ever see a game_id, never a _Game, so it needs no public API of its
    # own; GameRegistry reads and writes its fields directly.
    """One registry entry: a session plus the seats and connection state
    around it. Private to this package -- callers only ever see a game_id."""

    def __init__(self, session):
        self.session = session
        self.seats = {}          # username -> "w" | "b" | "viewer"
        self.connected = set()   # usernames currently connected
        self.ended = False       # has GAME_END already been published?
        self.linger_ms = 0       # ms accumulated since ended became True
        self.away_ms = {}        # username -> ms disconnected so far,
        #                          for currently-away SEATED ("w"/"b")
        #                          players only -- see GameRegistry's own
        #                          leave()/join()/advance()
