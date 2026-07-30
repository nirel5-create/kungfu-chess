"""Async WebSocket server for Kung-Fu Chess.

app.py's local frame loop is clock.tick() -> engine.snapshot() ->
renderer.render(). This file keeps the first half of that loop -- the clock
and the engine -- and moves the second half to whichever clients are
connected: every ~30 ms it advances every live game and broadcasts each
game's protocol.state(session.snapshot()) to the clients sitting in that
game, so each window redraws the same board as the others in its game.
Commands travel the other way: a client sends a `move`/`jump` message, this
file decodes it with protocol.loads and hands it to GameSession.submit -- it
never builds or applies a command itself.

What this file owns: the websocket connections, the tick interval, and
broadcasting. What it does NOT own: which games exist, seats, or lifecycle --
that is common.registry.GameRegistry; nor game rules or command handling --
that is common.net.GameSession, one layer below the registry. This file is
plumbing only, and is not unit-tested, the same way app.py's real OpenCV
window is not: a live socket cannot be driven from a test without becoming
an integration test. GameRegistry and GameSession are fully covered by
tests/unit/test_registry.py and tests/unit/test_session.py.

Step 5 fixes a real bug: this file used to build ONE GameSession at startup
and keep it forever, so once its king fell every later arrival got a
permanently-finished game and closed immediately. Now the server holds MANY
games via GameRegistry, and _find_or_create_game (below) is a small, clearly
separate policy function that decides which game a new connection joins --
today, everyone shares one open game, creating a fresh one when none is
open. Play (slide 5) and Room (slide 6) will later replace only that one
function; GameRegistry itself needs no change for either.

Colors are assigned by GameRegistry.join, by connection order within a game
(Step 4): the first to join a game is seated "w", the second "b", and any
later joiner becomes a "viewer" that can watch but never move. This is the
"server knows WHO you are" half of the ownership design in common.net --
GameSession.submit is the half that enforces it.

At startup this also connects to Postgres (common.db) and makes sure the
players schema exists. Accounts, login, and ELO are later steps -- Step A
only proves the connection and puts the schema in place. Live games do not
depend on the database, so a failed connection is logged and the server
keeps serving games regardless; this is what makes that design-doc claim
true rather than merely asserted.

Run with:  python server.py
"""

import asyncio
import logging

import websockets

from common import db, net, protocol, topics
from common.bus import Bus
from common.logsetup import add_file_logging
from common.registry import AlreadyConnectedError, GameRegistry
from engine.game import GameEngine
from model.board import Board
from model.config import Config

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
_TICK_MS = 30
_LOG_PATH = "logs/server.log"
# Not the per-tick state broadcast itself -- that is ~33 lines/second and
# would make the log file useless within seconds (slide 6 asks for logs
# that can be inspected afterward, not a firehose). A summary every 10s is
# enough to show the loop is alive without doing that.
_SUMMARY_INTERVAL_MS = 10_000

# Matches app.py's build_game(): the crystal board asset has a thin decorative
# frame, so cells are 98px and the first cell starts 13px in, 15px down. The
# client draws with the same asset, so the pixel positions in every snapshot
# only line up if both sides use this same Config.
_CONFIG = Config(cell_size=98, board_offset=(13, 15))

_START = [
    ["bR", "bN", "bB", "bQ", "bK", "bB", "bN", "bR"],
    ["bP", "bP", "bP", "bP", "bP", "bP", "bP", "bP"],
    [".", ".", ".", ".", ".", ".", ".", "."],
    [".", ".", ".", ".", ".", ".", ".", "."],
    [".", ".", ".", ".", ".", ".", ".", "."],
    [".", ".", ".", ".", ".", ".", ".", "."],
    ["wP", "wP", "wP", "wP", "wP", "wP", "wP", "wP"],
    ["wR", "wN", "wB", "wQ", "wK", "wB", "wN", "wR"],
]

_log = logging.getLogger(__name__)


def _build_session():  # pragma: no cover
    board = Board([row[:] for row in _START], _CONFIG)
    engine = GameEngine(board, _CONFIG)
    return net.GameSession(engine)


async def _send_state(websocket, session):  # pragma: no cover
    await websocket.send(protocol.dumps(protocol.state(session.snapshot())))


async def _read_username(websocket):  # pragma: no cover
    """The username from the client's first message (a `login`), or "?" if
    the connection closes or sends something else before logging in. A
    missing username never blocks a seat from being assigned -- this is
    presentation only (slide 3: "just for presentation"), there is no
    account system to fail against (that is a later step)."""
    try:
        raw = await websocket.recv()
        message = protocol.loads(raw)
    except (protocol.ProtocolError, websockets.ConnectionClosed):
        return "?"
    if message.get("type") != protocol.LOGIN:
        return "?"
    return message["username"]


def _find_or_create_game(registry):  # pragma: no cover
    """This step's placeholder policy: everyone shares one open game, and a
    new one is created when none is open. Play (slide 5) and Room (slide 6)
    replace THIS FUNCTION and nothing else -- which is the point of keeping
    it separate from GameRegistry. "Open" means the game exists and is not
    yet game_over; a finished game is skipped, which is what fixes the
    reported bug -- a new arrival never gets handed a permanently-ended
    game."""
    for game_id in registry.game_ids():
        session = registry.session(game_id)
        if session is not None and not session.game_over:
            return game_id
    game_id = registry.create()
    _log.info("created game %s", game_id)
    return game_id


async def _handle_client(websocket, registry, clients):  # pragma: no cover
    """One coroutine per connection: read the login username the client
    sends first, join the policy-chosen game, send `assigned` before the
    first `state` so the client knows its role from the outset, register
    the connection, then apply every command it sends -- checked against
    its seat by GameSession.submit -- until it disconnects, at which point
    it leaves the game (its seat stays held; see GameRegistry.leave).

    A username already connected to the game it would join gets refused
    outright (GameRegistry.AlreadyConnectedError) rather than seated as a
    silent "viewer" -- this connection is closed right away, before it is
    ever added to `clients` or sent anything but the `error`, so it never
    reaches the command loop or GameRegistry.leave below."""
    username = await _read_username(websocket)
    game_id = _find_or_create_game(registry)
    try:
        color = registry.join(game_id, username)
    except AlreadyConnectedError:
        _log.warning("refused %s: already connected to game %s", username, game_id)
        await websocket.send(protocol.dumps(protocol.error("already_connected")))
        await websocket.close()
        return
    clients[websocket] = (game_id, username)
    _log.info("%s joined game %s as %s", username, game_id, color)
    try:
        await websocket.send(protocol.dumps(protocol.assigned(color)))
        await _send_state(websocket, registry.session(game_id))
        async for raw in websocket:
            try:
                message = protocol.loads(raw)
            except protocol.ProtocolError:
                _log.exception("dropping malformed frame from %s in game %s",
                                username, game_id)
                continue
            session = registry.session(game_id)
            if session is None:
                continue  # the game's linger period already elapsed
            applied = session.submit(message, registry.color_of(game_id, username))
            _log.info("%s %s from %s in game %s",
                       "applied" if applied else "refused", message.get("type"),
                       username, game_id)
    finally:
        clients.pop(websocket, None)
        registry.leave(game_id, username)
        _log.info("%s disconnected from game %s", username, game_id)


async def _tick_loop(registry, clients):  # pragma: no cover
    """Advance every game by a fixed step on a fixed interval, then push
    each game's own snapshot only to the clients sitting in that game.
    Today every client shares one game (see _find_or_create_game); once
    Room exists they will not, and broadcasting per-game already handles
    that -- Room needs no change here. A client whose send fails (it
    dropped the connection) is removed from `clients` rather than stopping
    the broadcast for everyone else.

    Also logs a summary every _SUMMARY_INTERVAL_MS (tick count, live games,
    connected clients) -- never the per-tick broadcast itself; see
    _SUMMARY_INTERVAL_MS's comment for why not."""
    tick_count = 0
    ms_since_summary = 0
    while True:
        await asyncio.sleep(_TICK_MS / 1000)
        registry.advance(_TICK_MS)
        tick_count += 1
        ms_since_summary += _TICK_MS
        if ms_since_summary >= _SUMMARY_INTERVAL_MS:
            ms_since_summary = 0
            # Known gap, seen live in this summary (live_games=0,
            # connected_clients=3): a client is never told its game was
            # removed after the linger period elapses (GameRegistry drops
            # it silently, see common/registry.py's GAME_END_LINGER_MS),
            # so `clients` can outlive every game_ids() entry it points
            # at. Those clients stay connected, attached to a game_id
            # registry.session() now returns None for, and see a frozen
            # board (the tick loop's per-game send below simply has
            # nothing to send them). Not fixed here -- noted because this
            # summary is what makes it visible at all.
            _log.info("tick=%d live_games=%d connected_clients=%d",
                       tick_count, len(registry.game_ids()), len(clients))
        dead = set()
        for game_id in registry.game_ids():
            session = registry.session(game_id)
            if session is None:
                continue
            message = protocol.dumps(protocol.state(session.snapshot()))
            for websocket, (client_game_id, _username) in clients.items():
                if client_game_id != game_id:
                    continue
                try:
                    await websocket.send(message)
                except websockets.ConnectionClosed:
                    dead.add(websocket)
        for websocket in dead:
            clients.pop(websocket, None)


def _connect_db():  # pragma: no cover
    """Connect to Postgres and make sure the players schema exists. Live
    games do not depend on the database (Server_Design.md section 10), so a
    failed connection is logged and swallowed here rather than raised --
    the caller starts the game server either way."""
    try:
        conn = db.connect()
        db.ensure_schema(conn)
        _log.info("connected to Postgres and verified the players schema")
    except Exception:  # pylint: disable=broad-except
        # Deliberate: any failure here (unset DATABASE_URL, unreachable
        # host, auth failure) must not stop the game server from starting,
        # per the design doc's claim that live games do not depend on the
        # database.
        _log.exception("could not reach Postgres; continuing without it")


async def _main():  # pragma: no cover
    _log.info("starting kung-fu chess server")
    _connect_db()
    bus = Bus()
    # Nothing else subscribes to GAME_START yet -- publishing it
    # unconditionally from here on is what lets ELO (a later step) attach
    # as a bus subscriber, with no change to GameRegistry or this file.
    # GAME_END gets one subscriber here, purely to log the winner: this is
    # the only place that knows how to turn a game_id into a log line, so
    # it belongs here rather than in GameRegistry, which does not log.
    bus.subscribe(topics.GAME_END, lambda payload: _log.info(
        "game %s ended, winner=%s", payload["game_id"], payload["winner"]))
    # king_type is passed explicitly rather than left at GameRegistry's own
    # default: both currently say "K", but that is one fact declared twice.
    # If _CONFIG's king token ever changed, an implicit default here would
    # silently desync -- the registry would keep detecting game_over
    # correctly (that comes from the engine) but _winner_of would find no
    # matching king and report winner=None forever.
    registry = GameRegistry(_build_session, bus=bus, king_type=_CONFIG.king_type)
    clients = {}  # websocket -> (game_id, username)

    async def handler(websocket):
        await _handle_client(websocket, registry, clients)

    async with websockets.serve(handler, _HOST, _PORT):
        _log.info("listening on ws://%s:%d", _HOST, _PORT)
        await _tick_loop(registry, clients)


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    # Console (above) is for watching a session live; the file (below) is
    # for looking at one afterward -- slide 6 wants both, and this is what
    # makes there be a file to look at. Shared with client.py, so the two
    # log files cannot drift into different formats.
    add_file_logging(_LOG_PATH)
    # Docker's HEALTHCHECK (see Dockerfile) opens a bare TCP socket to our
    # port every 10s and closes it again without ever sending a WebSocket
    # handshake -- websockets logs that as an ERROR with a full traceback,
    # on its own "websockets.server" logger, every single time. That is
    # our own healthcheck probing the port, not a real error, and at one
    # every 10s it would drown out everything slide 6 actually wants this
    # log for. Raising the level on that ONE logger -- not root, and not
    # our own __main__ logger below, which keeps logging at INFO exactly
    # as before -- is what silences just this noise and nothing else.
    logging.getLogger("websockets.server").setLevel(logging.CRITICAL)
    asyncio.run(_main())
