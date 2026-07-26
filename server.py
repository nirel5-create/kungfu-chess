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

Run with:  python server.py
"""

import asyncio
import logging

import websockets

from common import net, protocol
from engine.game import GameEngine
from model.board import Board
from model.config import Config

_HOST = "localhost"
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


async def _main():  # pragma: no cover
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
