"""ServerState: every collaborator server.connection, server.tick and
server.matchmaking thread through call after call, bundled into one object
instead of passed as separate parameters everywhere they are used together.
"""

from collections import namedtuple


class _PlayQueue:  # pylint: disable=too-few-public-methods
    """Play's queue and its per-connection wait boxes, together: the pure
    pairing queue (common.matchmaker.MatchMaker) and the {username:
    (websocket, future, rating)} boxes the tick loop resolves once paired
    or timed out -- see server.matchmaking's own module docstring. The
    two are bundled because they are always used together and nothing
    outside server.matchmaking/server.tick touches either, unlike
    ServerState's other fields."""

    def __init__(self, matchmaker):
        self.matchmaker = matchmaker
        self.matchmaking = {}


class ServerState:  # pylint: disable=too-few-public-methods
    """Which games exist and their seats (registry), which websocket is in
    which game (clients), the one default shared game_id box
    (default_game), the Postgres connection (db_conn, None if
    unreachable), Play's queue and wait boxes (play_queue), the
    server-wide duplicate-login guard (connected_usernames), and each
    game's own move-history tracker (observers).

    Built once by server.composition.main() and never rebuilt: every
    field here lives for the server's whole process lifetime, unlike a
    single connection's or a single tick's own local values -- registry
    and matchmaker are handed in already constructed (the composition
    root builds them; this class only bundles them) rather than built
    here, the same injection style GameRegistry itself already uses for
    make_session."""

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
