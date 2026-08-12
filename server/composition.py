"""The composition root: wires every collaborator together and starts
listening. Nothing else in `server` imports this module -- everything else
is a piece `main` assembles.
"""

import logging

import websockets

from common import topics
from common.bus import Bus
from common.matchmaker import MatchMaker
from common.registry import GameRegistry
from server.connection import _handle_client
from server.ratings import _connect_db, _update_ratings_on_game_end
from server.session import CONFIG, build_session
from server.state import ServerState
from server.tick import _tick_loop

LOG_PATH = "logs/server.log"

# "localhost" binds only to the loopback interface *inside* whatever network
# namespace the process runs in. On the host that is fine -- the interface a
# local client connects to and the one the server binds to are the same
# loopback. Inside a container it is not: Docker's published port
# (docker-compose.yml `ports: ["8765:8765"]`) forwards an external
# connection onto the container's real network interface, not its loopback,
# so a server bound only to loopback never sees that connection -- the
# client gets a TCP connection that opens and then closes with zero bytes,
# exactly the failure this was. Binding to 0.0.0.0 listens on every
# interface instead, including the one Docker forwards to. This is safe
# here specifically because Docker only exposes to the host the ports this
# project's own docker-compose.yml explicitly publishes -- 0.0.0.0 inside
# the container is not the same exposure as 0.0.0.0 on a bare host.
_HOST = "0.0.0.0"
_PORT = 8765

_log = logging.getLogger(__name__)


async def main():  # pragma: no cover
    """Connect to Postgres (best-effort), wire the registry/matchmaker/bus,
    and serve forever."""
    _log.info("starting kung-fu chess server")
    db_conn = _connect_db()
    bus = Bus()
    # Nothing else subscribes to GAME_START yet -- publishing it
    # unconditionally from here on is what lets a future subscriber attach
    # with no change to GameRegistry or this file. GAME_END gets three
    # subscribers here: one purely to log the winner (this is the only
    # place that knows how to turn a game_id into a log line, so it
    # belongs here rather than in GameRegistry, which does not log),
    # ended_games.append, and _record_rating_update -- the entire rating
    # half of this server, plus its rating push, is these two small
    # hand-off lists, exactly as GameRegistry's own module docstring says
    # the bus was built to allow. Both hand-offs exist because Bus.publish
    # is synchronous, so a subscriber cannot itself await a
    # websocket.send; see server.tick's own docstring for why each is a
    # plain list rather than an async mechanism.
    bus.subscribe(topics.GAME_END, lambda payload: _log.info(
        "game %s ended, winner=%s", payload["game_id"], payload["winner"]))
    ended_games = []  # GAME_END payloads awaiting server.tick's next broadcast
    bus.subscribe(topics.GAME_END, ended_games.append)
    # (username, new_rating) pairs awaiting server.tick's next push --
    # appended here rather than inside _update_ratings_on_game_end itself,
    # which stays a pure "read the payload, write the database" function
    # with no knowledge of connections or the bus, the same separation
    # ended_games.append already keeps for the outcome broadcast.
    rating_updates = []

    def _record_rating_update(payload):
        result = _update_ratings_on_game_end(db_conn, payload)
        if result is not None:
            white_user, new_white, black_user, new_black = result
            rating_updates.append((white_user, new_white))
            rating_updates.append((black_user, new_black))

    bus.subscribe(topics.GAME_END, _record_rating_update)
    # king_type is passed explicitly rather than left at GameRegistry's own
    # default: both currently say "K", but that is one fact declared twice.
    # If CONFIG's king token ever changed, an implicit default here would
    # silently desync -- the registry would keep detecting game_over
    # correctly (that comes from the engine) but its own winner lookup
    # would find no matching king and report winner=None forever.
    registry = GameRegistry(build_session, bus=bus, king_type=CONFIG.king_type)
    matchmaker = MatchMaker()  # see server.matchmaking._play_matchmaking
    state = ServerState(registry, db_conn, matchmaker)

    async def handler(websocket):
        await _handle_client(websocket, state)

    async with websockets.serve(handler, _HOST, _PORT):
        _log.info("listening on ws://%s:%d", _HOST, _PORT)
        await _tick_loop(state, ended_games, rating_updates)
