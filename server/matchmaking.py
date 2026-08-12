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
    """Enqueue `username` in `state.play_queue.matchmaker` (Play) and wait
    for server.tick's own tick loop to either pair them or time them out.

    -> (game_id, color) once the tick loop has paired and joined this
    connection -- it has also already sent matchmaking("found") and
    assigned(color) by then, see _seat_matched_pair -- or None once timed
    out (matchmaking("timeout") already sent, see
    _report_matchmaking_timeout) or once this connection's own socket
    closes while still queued.

    `state.play_queue.matchmaking` is a {username: (websocket, future,
    rating)} box, the same shape `state.clients` has for joined
    connections: the tick loop needs a way to reach a WAITING
    connection's own websocket (nothing else has it -- there is no
    game_id yet), and needs `future` to hand the outcome back to this
    coroutine and `rating` to log a pairing or timeout without asking the
    database again.

    A disconnect while queued is detected by racing `future` (resolved by
    the tick loop) against websocket.wait_closed(): otherwise nothing here
    is reading the socket, so a closed connection would go unnoticed
    until it eventually timed out on its own, up to a minute later --
    during which the tick loop could still pair it with a live opponent,
    who would then be waiting on someone already gone."""
    rating = _current_rating(state.db_conn, username)
    future = asyncio.get_running_loop().create_future()
    state.play_queue.matchmaking[username] = (websocket, future, rating)
    state.play_queue.matchmaker.enqueue(username, rating)
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
        state.play_queue.matchmaker.cancel(username)
        state.play_queue.matchmaking.pop(username, None)


async def _seat_matched_pair(state, user_a, user_b):  # pragma: no cover
    """Create a fresh game for `user_a`/`user_b` (a Play match), join
    both, and tell each matchmaking("found") then assigned(color), in
    that order -- protocol.matchmaking's own docstring promises `found`
    is followed by `assigned`.

    `state.play_queue.matchmaking[username]` is always present here:
    matchmaker.advance() can only return a username that was still in ITS
    OWN queue at that exact moment, and _play_matchmaking -- the only
    thing that ever removes a username from either the matchmaker or
    `state.play_queue.matchmaking` -- always removes both together,
    synchronously, with no `await` between the two removals.

    A player whose socket already died while queued (a narrow race with
    _play_matchmaking's own disconnect detection) is still seated here,
    since GameRegistry has no way to know otherwise, but is immediately
    left again the moment its found/assigned send fails: this hands the
    surviving opponent straight into the ordinary disconnect countdown
    instead of leaving it waiting on a partner who was never really
    there."""
    game_id = state.registry.create()
    for username in (user_a, user_b):
        websocket, future, rating = state.play_queue.matchmaking[username]
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


async def _report_matchmaking_timeout(matchmaking, username):  # pragma: no cover
    """Tell a timed-out seeker their search found nobody, and release
    their _play_matchmaking coroutine. `matchmaking[username]` is always
    present here -- see _seat_matched_pair's own docstring for why."""
    websocket, future, rating = matchmaking[username]
    try:
        await websocket.send(protocol.dumps(protocol.matchmaking("timeout")))
    except websockets.ConnectionClosed:
        pass
    future.set_result(None)
    _log.info("%s (rating %d) timed out waiting for a match", username, rating)
