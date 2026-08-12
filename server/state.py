"""ServerState: every collaborator server.connection, server.tick and
server.matchmaking thread through call after call, bundled into one object
instead of passed as separate parameters everywhere they are used together.
"""

from collections import namedtuple


class _PlayQueue:
    """Play's queue and its per-connection wait boxes, together: the pure
    pairing queue (common.matchmaker.MatchMaker) and the {username:
    (websocket, future, rating)} boxes the tick loop resolves once paired
    or timed out. Exposes methods for both instead of the two collaborators
    directly, so server.matchmaking/server.tick call one thing, not two."""

    def __init__(self, matchmaker):
        self.matchmaker = matchmaker
        self.matchmaking = {}

    def enqueue(self, username, rating, websocket, future):  # pragma: no cover
        """Register `username`'s wait box and enter them into the
        matchmaker's queue at `rating`."""
        self.matchmaking[username] = (websocket, future, rating)
        self.matchmaker.enqueue(username, rating)

    def cancel(self, username):  # pragma: no cover
        """Drop `username` from the matchmaker's queue and its wait box.
        A no-op for a username not currently waiting."""
        self.matchmaker.cancel(username)
        self.matchmaking.pop(username, None)

    def advance(self, ms):  # pragma: no cover
        """-> (pairs, timed_out) for this tick; see MatchMaker.advance."""
        return self.matchmaker.advance(ms)

    def waiting_entry(self, username):  # pragma: no cover
        """-> (websocket, future, rating) for `username`'s wait box."""
        return self.matchmaking[username]


class ServerState:  # pylint: disable=too-few-public-methods
    """Every collaborator server.connection, server.tick and
    server.matchmaking thread through together: the registry, which
    websocket is in which game, the default shared game_id box, the
    Postgres connection (None if unreachable), Play's queue, the
    duplicate-login guard, and each game's history tracker."""

    def __init__(self, registry, db_conn, matchmaker):
        self.registry = registry
        self.clients = {}  # websocket -> (game_id, username)
        self.default_game = {"id": None}  # see server.rooms._find_or_create_game
        self.db_conn = db_conn
        self.play_queue = _PlayQueue(matchmaker)
        self.connected_usernames = set()  # see server.auth._reserve_username
        self.observers = {}  # game_id -> CaptureLog; see server.history._observer_for


# A seat, once gotten: which game, which color, and whose connection --
# server.connection._run_game_loop's own bundle, since websocket/state
# already collapse its other parameters and this is the one remaining
# group of three values that always travel together.
Seat = namedtuple("Seat", "game_id color username")
