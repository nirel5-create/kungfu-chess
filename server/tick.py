"""The tick loop: advances every live game by a fixed step on a fixed
interval, then broadcasts whatever changed to whichever clients are
sitting in each game -- state, waiting-for-opponent, game-over, history,
and disconnect countdown -- and drives Play's matchmaking and the
periodic activity summary.
"""

import asyncio
import logging

import websockets

from common import protocol
from server.history import _observer_for, _seat_names
from server.matchmaking import _seat_matched_pair, _report_matchmaking_timeout

_log = logging.getLogger(__name__)

_TICK_MS = 30

# Not the per-tick state broadcast itself -- that is ~33 lines/second and
# would make the log file useless within seconds. A summary every 10s is
# enough to show the loop is alive without doing that.
_SUMMARY_INTERVAL_MS = 10_000


def _winner_username(seats, winner):
    """-> the username sitting in the `winner` seat, or None if there is
    no winner, or (defensively) if the winning color was somehow never
    seated -- should not happen, since `winner` can only ever be a color
    GameRegistry itself found seated."""
    if winner is None:
        return None
    return next((user for user, color in seats.items() if color == winner), None)


class _TickState:  # pylint: disable=too-few-public-methods
    """Bookkeeping that persists from one tick to the next: the running
    tick count, time since the last summary, and what was last sent per
    game_id or (game_id, username), for the send-on-change broadcasts
    below. `current_countdown_seconds` is rebuilt empty each tick and
    becomes `last_countdown_seconds` once that tick's broadcasts are done."""

    def __init__(self):
        self.tick_count = 0
        self.ms_since_summary = 0
        self.last_countdown_seconds = {}
        self.current_countdown_seconds = {}
        self.last_history_sent = {}
        self.last_waiting_sent = {}


class _GameBroadcast:  # pylint: disable=too-few-public-methods
    """The three things every per-game broadcast needs: which game, who
    is currently connected to it, and the shared dead-socket accumulator
    for the whole tick -- bundled so each broadcast function below takes
    one object, and the send-to-everyone-move-failures-into-dead sequence
    is written once, as a method."""

    def __init__(self, game_id, game_clients, dead):
        self.game_id = game_id
        self.game_clients = game_clients
        self.dead = dead

    async def send(self, message):
        """Send `message` to every client in this game, moving any whose
        send fails into the shared `dead` set instead of raising."""
        for websocket in self.game_clients:
            try:
                await websocket.send(message)
            except websockets.ConnectionClosed:
                self.dead.add(websocket)


async def _broadcast_state(session, broadcast):  # pragma: no cover
    await broadcast.send(protocol.dumps(protocol.state(session.snapshot())))


async def _broadcast_waiting_if_changed(state, broadcast, tick_state):  # pragma: no cover
    """Broadcast a game's waiting-for-opponent status whenever it changes.
    Display only: server.connection already refuses to forward a
    move/jump while a seat is empty, so a client that missed this message
    can only fail to see why nothing moves, never exploit the gap."""
    is_waiting = not state.registry.both_seated(broadcast.game_id)
    if tick_state.last_waiting_sent.get(broadcast.game_id) == is_waiting:
        return
    tick_state.last_waiting_sent[broadcast.game_id] = is_waiting
    await broadcast.send(protocol.dumps(protocol.waiting(is_waiting)))


async def _broadcast_game_over_if_ended(ended_by_game_id, broadcast):  # pragma: no cover
    """Broadcast the outcome once a game ends, using this tick's own
    GAME_END payloads: GameRegistry.advance publishes them synchronously,
    so every game that ended this tick is already in `ended_by_game_id`.
    Sent once per game, to whichever clients are connected to it right
    now."""
    ended_payload = ended_by_game_id.get(broadcast.game_id)
    if ended_payload is None:
        return
    winner = ended_payload["winner"]
    winner_username = _winner_username(ended_payload["seats"], winner)
    await broadcast.send(protocol.dumps(protocol.game_over(winner, winner_username)))


async def _broadcast_history_if_changed(state, broadcast, session, tick_state):  # pragma: no cover
    """Run this game's CaptureLog every tick, but only broadcast its
    log/scores/names when `(log length, white_name, black_name)` differs
    from what was last sent -- log length alone is enough to also cover
    score, since a score only ever changes together with a new log
    entry."""
    observer = _observer_for(state.observers, broadcast.game_id)
    observer.observe(session.snapshot(), tick_state.tick_count * _TICK_MS)
    white_name, black_name = _seat_names(state.registry.seats(broadcast.game_id))
    history_key = (len(observer.log()), white_name, black_name)
    if tick_state.last_history_sent.get(broadcast.game_id) == history_key:
        return
    tick_state.last_history_sent[broadcast.game_id] = history_key
    await broadcast.send(protocol.dumps(protocol.history(
        white_name, black_name, observer.score_of("w"), observer.score_of("b"), observer.log())))


async def _broadcast_countdown(state, broadcast, tick_state):  # pragma: no cover
    """Send protocol.countdown(seconds) for each away player, in whole
    seconds and only when the value changed since the last tick. Never
    called for a game that has already ended, so a last-tick countdown
    never flashes over the GAME OVER banner."""
    for username, ms_left in state.registry.countdown_ms(broadcast.game_id).items():
        seconds = -(-ms_left // 1000)  # ceiling: show 20..1, never a 0 flash
        key = (broadcast.game_id, username)
        tick_state.current_countdown_seconds[key] = seconds
        if tick_state.last_countdown_seconds.get(key) == seconds:
            continue
        await broadcast.send(protocol.dumps(protocol.countdown(seconds)))


async def _broadcast_one_game(state, game_id, ended_by_game_id,
                               tick_state, dead):  # pragma: no cover
    """Every broadcast one game_id gets in one tick: state, waiting (on
    change), game-over (once), history (on change), and -- unless the
    game already ended -- the countdown, skipped there because a game can
    end the exact same tick an away player's countdown reaches 0. A no-op
    if the game's linger period already elapsed."""
    session = state.registry.session(game_id)
    if session is None:
        return
    game_clients = [websocket for websocket, (client_game_id, _username)
                     in state.clients.items() if client_game_id == game_id]
    broadcast = _GameBroadcast(game_id, game_clients, dead)
    await _broadcast_state(session, broadcast)
    await _broadcast_waiting_if_changed(state, broadcast, tick_state)
    await _broadcast_game_over_if_ended(ended_by_game_id, broadcast)
    await _broadcast_history_if_changed(state, broadcast, session, tick_state)
    if not session.game_over:
        await _broadcast_countdown(state, broadcast, tick_state)


async def _advance_matchmaking(state):  # pragma: no cover
    """Run one tick of Play's matchmaking: every pair gets a fresh game,
    every timeout gets told, and both resolve that connection's own
    _play_matchmaking future -- the actual hand-off back to the waiting
    coroutine. A direct call rather than the bus, since there is exactly
    one interested party per outcome."""
    pairs, timed_out = state.play_queue.advance(_TICK_MS)
    for user_a, user_b in pairs:
        await _seat_matched_pair(state, user_a, user_b)
    for username in timed_out:
        await _report_matchmaking_timeout(state.play_queue, username)


async def _push_rating_updates(state, rating_updates, dead):  # pragma: no cover
    """Push a fresh rating to any still-connected player named in
    `rating_updates` -- a plain list of (username, new_rating) pairs a
    GAME_END subscriber appends to. A reverse username -> websocket scan
    over `state.clients`, since that is the only place a still-connected
    player's socket can be found."""
    for username, new_rating in rating_updates:
        websocket = next((ws for ws, (_gid, user) in state.clients.items()
                           if user == username), None)
        if websocket is not None:
            try:
                await websocket.send(protocol.dumps(protocol.rating(new_rating)))
            except websockets.ConnectionClosed:
                dead.add(websocket)
    rating_updates.clear()


def _log_summary_if_due(state, tick_state):  # pragma: no cover
    """Log a summary every _SUMMARY_INTERVAL_MS (tick count, live games,
    connected clients) -- never the per-tick broadcast itself, which
    would flood the log within seconds. Known gap this can surface: a
    client is never told its game was removed after the linger period,
    so it can stay connected to a game_id that no longer exists."""
    tick_state.ms_since_summary += _TICK_MS
    if tick_state.ms_since_summary < _SUMMARY_INTERVAL_MS:
        return
    tick_state.ms_since_summary = 0
    _log.info("tick=%d live_games=%d connected_clients=%d",
               tick_state.tick_count, len(state.registry.game_ids()), len(state.clients))


def _prune_stale_games(state, tick_state):  # pragma: no cover
    """Drop bookkeeping for any game_id no longer in registry.game_ids()
    -- a finished-and-removed game's observer, and this tick_state's own
    last-sent history/waiting entries for it, are not kept forever."""
    live_game_ids = set(state.registry.game_ids())
    for stale_id in set(state.observers) - live_game_ids:
        del state.observers[stale_id]
        tick_state.last_history_sent.pop(stale_id, None)
        tick_state.last_waiting_sent.pop(stale_id, None)


async def _tick_loop(state, ended_games, rating_updates):  # pragma: no cover
    """Advance every game by a fixed step, then push each game's own
    broadcasts only to the clients sitting in that game; also runs Play's
    matchmaking, pushes fresh ratings, and logs the periodic summary. A
    client whose send fails is collected into `dead` for the whole tick,
    so one failure does not stop any other client's broadcast."""
    tick_state = _TickState()
    while True:
        await asyncio.sleep(_TICK_MS / 1000)
        state.registry.advance(_TICK_MS)
        await _advance_matchmaking(state)
        tick_state.tick_count += 1
        _log_summary_if_due(state, tick_state)
        dead = set()
        tick_state.current_countdown_seconds = {}
        ended_by_game_id = {payload["game_id"]: payload for payload in ended_games}
        ended_games.clear()
        await _push_rating_updates(state, rating_updates, dead)
        for game_id in state.registry.game_ids():
            await _broadcast_one_game(state, game_id, ended_by_game_id, tick_state, dead)
        tick_state.last_countdown_seconds = tick_state.current_countdown_seconds
        _prune_stale_games(state, tick_state)
        for websocket in dead:
            state.clients.pop(websocket, None)
