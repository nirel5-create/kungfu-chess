"""Async WebSocket server for Kung-Fu Chess.

app.py's local frame loop is clock.tick() -> engine.snapshot() ->
renderer.render(). This file keeps the first half of that loop -- the clock
and the engine -- and moves the second half to whichever clients are
connected: every ~30 ms it advances the one GameSession and broadcasts
protocol.state(session.snapshot()) to every client, so each window redraws the
same board. Commands travel the other way: a client sends a `move`/`jump`
message, this file decodes it with protocol.loads and hands it to
GameSession.submit -- it never builds or applies a command itself.

What this file owns: the websocket connections, the tick interval, and
broadcasting. What it does NOT own: game rules or command handling -- both
live in common.net.GameSession, the one place a message becomes an engine
call, so this file is plumbing only. It is not unit-tested, the same way
app.py's real OpenCV window is not: a live socket cannot be driven from a
test without becoming an integration test. GameSession itself is fully
covered by tests/unit/test_session.py.

Two-player colour assignment, rooms, and login are later steps: for now every
connected client shares the one session and may move any piece.

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

from common import db, net, protocol
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


async def _handle_client(websocket, session, clients):  # pragma: no cover
    """One coroutine per connection: register it, send the current state so
    the new window is never blank, then apply every command it sends until it
    disconnects."""
    clients.add(websocket)
    try:
        await _send_state(websocket, session)
        async for raw in websocket:
            try:
                message = protocol.loads(raw)
            except protocol.ProtocolError:
                _log.exception("dropping malformed frame from a client")
                continue
            session.submit(message)
    finally:
        clients.discard(websocket)


async def _tick_loop(session, clients):  # pragma: no cover
    """Advance the session by a fixed step on a fixed interval, then push the
    resulting snapshot to everyone. A client whose send fails (it dropped the
    connection) is removed from the set rather than stopping the broadcast."""
    while True:
        await asyncio.sleep(_TICK_MS / 1000)
        session.advance(_TICK_MS)
        message = protocol.dumps(protocol.state(session.snapshot()))
        dead = set()
        for websocket in clients:
            try:
                await websocket.send(message)
            except websockets.ConnectionClosed:
                dead.add(websocket)
        clients.difference_update(dead)


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
    _connect_db()
    session = _build_session()
    clients = set()

    async def handler(websocket):
        await _handle_client(websocket, session, clients)

    async with websockets.serve(handler, _HOST, _PORT):
        _log.info("listening on ws://%s:%d", _HOST, _PORT)
        await _tick_loop(session, clients)


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
