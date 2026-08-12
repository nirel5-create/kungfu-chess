"""Play: queuing a connection for a rating-matched opponent, and turning a
pairing or a timeout (both decided by common.matchmaker.MatchMaker, driven
once per tick from server.tick) into messages and a seat.
"""

import asyncio
import logging

import websockets

from common import protocol
from server.auth import _current_rating

_log = logging.getLogger(__name__)


async def _play_matchmaking(websocket, state, username):  # pragma: no cover
    """Enqueue `username` in Play and wait for server.tick's own loop to
    pair or time it out. -> (game_id, color) once paired, or None once
    timed out or disconnected while queued. Races `future` against
    websocket.wait_closed() so a disconnect while queued is noticed at
    once, instead of possibly pairing a live opponent with someone gone."""
    rating = _current_rating(state.db_conn, username)
    future = asyncio.get_running_loop().create_future()
    state.play_queue.enqueue(username, rating, websocket, future)
    _log.info("%s entered matchmaking at rating %d", username, rating)
    try:
        await websocket.send(protocol.dumps(protocol.matchmaking("searching")))
        closed = asyncio.ensure_future(websocket.wait_closed())
        try:
            await asyncio.wait({future, closed}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            closed.cancel()
        return future.result() if future.done() else None
    except websockets.ConnectionClosed:
        return None
    finally:
        state.play_queue.cancel(username)


async def _seat_matched_pair(state, user_a, user_b):  # pragma: no cover
    """Create a fresh game for `user_a`/`user_b`, join both, and send each
    matchmaking("found") then assigned(color), in that order. A player
    whose socket already died while queued is still seated (GameRegistry
    can't know otherwise) but is immediately left again once its send
    fails, sending the survivor into the ordinary disconnect countdown."""
    game_id = state.registry.create()
    for username in (user_a, user_b):
        websocket, future, rating = state.play_queue.waiting_entry(username)
        color = state.registry.join(game_id, username)
        try:
            await websocket.send(protocol.dumps(protocol.matchmaking("found")))
            await websocket.send(protocol.dumps(protocol.assigned(color)))
        except websockets.ConnectionClosed:
            state.registry.leave(game_id, username)
            future.set_result(None)
        else:
            state.clients[websocket] = (game_id, username)
            future.set_result((game_id, color))
        _log.info("matched %s (rating %d) into game %s as %s",
                   username, rating, game_id, color)


async def _report_matchmaking_timeout(play_queue, username):  # pragma: no cover
    """Tell a timed-out seeker their search found nobody, and release
    their _play_matchmaking coroutine."""
    websocket, future, rating = play_queue.waiting_entry(username)
    try:
        await websocket.send(protocol.dumps(protocol.matchmaking("timeout")))
    except websockets.ConnectionClosed:
        pass
    future.set_result(None)
    _log.info("%s (rating %d) timed out waiting for a match", username, rating)
