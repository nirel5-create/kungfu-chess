"""ServerState: every collaborator server.connection, server.tick and
server.matchmaking thread through call after call, bundled into one object
instead of passed as separate parameters everywhere they are used together.
"""

from collections import namedtuple


class _PlayQueue:  # pylint: disable=too-few-public-methods
    """Play's queue and its per-connection wait boxes, together: the pure
    pairing queue (common.matchmaker.MatchMaker) and the {username:
    (websocket, future, rating)} boxes the tick loop resolves once paired
    or timed out. Bundled because nothing outside server.matchmaking and
    server.tick touches either one."""

    def __init__(self, matchmaker):
        self.matchmaker = matchmaker
        self.matchmaking = {}


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
