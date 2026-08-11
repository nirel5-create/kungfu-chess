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
    """-> the username sitting in the `winner` seat, or None if there is no
    winner (a game with no result reports no name, not a color -- see
    protocol.game_over's own docstring) or, defensively, if the winning
    color was somehow never seated -- should not happen, since `winner` can
    only ever be a color GameRegistry itself found seated."""
    if winner is None:
        return None
    return next((user for user, color in seats.items() if color == winner), None)


async def _broadcast_countdown(registry, game_id, game_clients, current_countdown_seconds,
                                last_countdown_seconds, dead):  # pragma: no cover
                                # pylint: disable=too-many-arguments
                                # pylint: disable=too-many-positional-arguments
    """Send protocol.countdown(seconds) to every client in `game_clients`
    for each away player in `game_id` -- whole seconds, not milliseconds,
    and only when the value actually changed since the last tick
    (`last_countdown_seconds`), the same "send on change, not on every
    tick" reasoning _SUMMARY_INTERVAL_MS already uses. A client whose
    send fails is added to `dead`, the same convention every other
    per-tick broadcast in _tick_loop uses, rather than returned.

    Never called for a game that has already ended -- see _tick_loop's
    own docstring for why."""
    for username, ms_left in registry.countdown_ms(game_id).items():
        seconds = -(-ms_left // 1000)  # ceiling: show 20..1, never a 0 flash
        key = (game_id, username)
        current_countdown_seconds[key] = seconds
        if last_countdown_seconds.get(key) == seconds:
            continue
        countdown_message = protocol.dumps(protocol.countdown(seconds))
        for websocket in game_clients:
            try:
                await websocket.send(countdown_message)
            except websockets.ConnectionClosed:
                dead.add(websocket)


async def _tick_loop(registry, clients, ended_games, matchmaker, matchmaking,
                      observers, rating_updates):  # pragma: no cover
                      # pylint: disable=too-many-locals, too-many-branches
                      # pylint: disable=too-many-statements, too-many-arguments
                      # pylint: disable=too-many-positional-arguments
    """Advance every game by a fixed step on a fixed interval, then push
    each game's own snapshot only to the clients sitting in that game.
    Every client shares one game by default; a Room or a Play match does
    not, and broadcasting per-game already handles that. A client whose
    send fails (it dropped the connection) is removed from `clients`
    rather than stopping the broadcast for everyone else.

    Also broadcasts the disconnect countdown: for every LIVE game (not
    session.game_over -- see below) with an away player
    (GameRegistry.countdown_ms), send protocol.countdown(seconds) --
    whole seconds, not milliseconds, and only when the second actually
    changes for that (game, username) pair, the same "send on change, not
    on every tick" reasoning _SUMMARY_INTERVAL_MS already uses.
    `last_countdown_seconds` remembers what was last sent per (game_id,
    username) and is rebuilt from scratch every tick, which is what makes
    a countdown that stops (the player reconnected) simply stop appearing
    in it -- nothing to explicitly clean up.

    The game_over check exists because a game can end on the exact same
    tick an away player's own countdown reaches 0 (auto-resign): without
    it, that last countdown(0) still goes out alongside game_over,
    flashing "0s" over the GAME OVER banner for a game that is already
    decided -- there is nothing left to count down toward once it is.

    Also broadcasts the outcome once a game ends: `ended_games` is a plain
    list a GAME_END bus subscriber appends its payload to (see
    server.composition) -- GameRegistry.advance publishes GAME_END synchronously,
    from inside the registry.advance(...) call below, so by the time this
    function reaches the per-game loop every game that just ended this
    tick is already in it. A game that ended stays in
    registry.game_ids() for its whole GAME_END_LINGER_MS afterward
    (common/registry), which is many ticks at _TICK_MS=30 -- comfortably
    longer than the one tick `ended_games` is ever allowed to hold an
    entry for (drained, in full, every tick below), so an ended game's id
    is always still there to match against. Sent once per game, to
    whichever clients are connected to it at that moment -- the same
    clients its final `state` broadcast just went to.

    Also runs Play's matchmaking: matchmaker.advance(_TICK_MS) once per
    tick, exactly like registry.advance -- time stays explicit here too.
    Every pair gets a fresh game (_seat_matched_pair); every timeout gets
    told (_report_matchmaking_timeout). Both also resolve that
    connection's own _play_matchmaking future, which is the actual
    hand-off back to _handle_client's waiting coroutine -- Bus-style
    pub/sub was not used here because there is exactly one interested
    party per outcome (the seeker's own connection), not an open set of
    subscribers.

    Also runs each game's own CaptureLog and broadcasts its current
    log/scores/names whenever they change: `observer.observe` runs every
    tick, unconditionally, same as the observer's own docstring expects
    ("called as often or as rarely as the view likes"), but the actual
    `history` message is only sent when `(log length, white_name,
    black_name)` differs from `last_history_sent[game_id]` -- log length
    alone is enough to also cover score, since a score only ever changes
    together with a new log entry. `observers`/`last_history_sent` are
    pruned for any game_id no longer in registry.game_ids() at the end of
    each tick, so a finished-and-removed game's observer is not kept
    forever.

    Also pushes a fresh rating to any still-connected player named in
    `rating_updates` -- a plain list of (username, new_rating) pairs a
    GAME_END subscriber appends to (see server.composition), mirroring
    `ended_games`' own hand-off pattern. Drained independently of the
    per-game_id loop below, by a reverse username -> websocket scan over
    `clients`, rather than nested inside that loop's own `ended_payload
    is not None` branch: the affected players are still in `clients`,
    under the game_id that just ended, for as long as _run_game_loop's
    own command loop keeps running on their connection (until they
    disconnect or pick a new game), which already outlives the one tick
    `ended_games` itself is drained within.

    Also broadcasts a game's waiting-for-opponent status whenever it
    CHANGES: `last_waiting_sent[game_id]` remembers the last value sent,
    the same send-on-change idiom `last_history_sent` already uses just
    below, since most ticks a game's seats do not change at all. This is
    display only -- _run_game_loop is what actually refuses to forward a
    move/jump while a seat is empty, so a client that somehow missed this
    message still cannot exploit the gap, only fail to see why nothing
    moves.

    Also logs a summary every _SUMMARY_INTERVAL_MS (tick count, live games,
    connected clients) -- never the per-tick broadcast itself; see
    _SUMMARY_INTERVAL_MS's comment for why not."""
    tick_count = 0
    ms_since_summary = 0
    last_countdown_seconds = {}  # (game_id, username) -> last-sent whole seconds
    last_history_sent = {}  # game_id -> (log length, white_name, black_name)
    last_waiting_sent = {}  # game_id -> last-sent waiting bool
    while True:
        await asyncio.sleep(_TICK_MS / 1000)
        registry.advance(_TICK_MS)
        pairs, timed_out = matchmaker.advance(_TICK_MS)
        for user_a, user_b in pairs:
            await _seat_matched_pair(registry, clients, matchmaking, user_a, user_b)
        for username in timed_out:
            await _report_matchmaking_timeout(matchmaking, username)
        tick_count += 1
        ms_since_summary += _TICK_MS
        if ms_since_summary >= _SUMMARY_INTERVAL_MS:
            ms_since_summary = 0
            # Known gap, seen live in this summary (live_games=0,
            # connected_clients=3): a client is never told its game was
            # removed after the linger period elapses (GameRegistry drops
            # it silently, see common/registry's GAME_END_LINGER_MS),
            # so `clients` can outlive every game_ids() entry it points
            # at. Those clients stay connected, attached to a game_id
            # registry.session() now returns None for, and see a frozen
            # board (the tick loop's per-game send below simply has
            # nothing to send them). Not fixed here -- noted because this
            # summary is what makes it visible at all.
            _log.info("tick=%d live_games=%d connected_clients=%d",
                       tick_count, len(registry.game_ids()), len(clients))
        dead = set()
        current_countdown_seconds = {}
        ended_by_game_id = {payload["game_id"]: payload for payload in ended_games}
        ended_games.clear()
        for username, new_rating in rating_updates:
            websocket = next((ws for ws, (_gid, user) in clients.items()
                               if user == username), None)
            if websocket is not None:
                try:
                    await websocket.send(protocol.dumps(protocol.rating(new_rating)))
                except websockets.ConnectionClosed:
                    dead.add(websocket)
        rating_updates.clear()
        for game_id in registry.game_ids():
            session = registry.session(game_id)
            if session is None:
                continue
            game_clients = [websocket for websocket, (client_game_id, _username)
                             in clients.items() if client_game_id == game_id]
            message = protocol.dumps(protocol.state(session.snapshot()))
            for websocket in game_clients:
                try:
                    await websocket.send(message)
                except websockets.ConnectionClosed:
                    dead.add(websocket)
            is_waiting = not registry.both_seated(game_id)
            if last_waiting_sent.get(game_id) != is_waiting:
                last_waiting_sent[game_id] = is_waiting
                waiting_message = protocol.dumps(protocol.waiting(is_waiting))
                for websocket in game_clients:
                    try:
                        await websocket.send(waiting_message)
                    except websockets.ConnectionClosed:
                        dead.add(websocket)
            ended_payload = ended_by_game_id.get(game_id)
            if ended_payload is not None:
                winner = ended_payload["winner"]
                winner_username = _winner_username(ended_payload["seats"], winner)
                game_over_message = protocol.dumps(protocol.game_over(winner, winner_username))
                for websocket in game_clients:
                    try:
                        await websocket.send(game_over_message)
                    except websockets.ConnectionClosed:
                        dead.add(websocket)
            observer = _observer_for(observers, game_id)
            observer.observe(session.snapshot(), tick_count * _TICK_MS)
            white_name, black_name = _seat_names(registry.seats(game_id))
            history_key = (len(observer.log()), white_name, black_name)
            if last_history_sent.get(game_id) != history_key:
                last_history_sent[game_id] = history_key
                history_message = protocol.dumps(protocol.history(
                    white_name, black_name,
                    observer.score_of("w"), observer.score_of("b"), observer.log()))
                for websocket in game_clients:
                    try:
                        await websocket.send(history_message)
                    except websockets.ConnectionClosed:
                        dead.add(websocket)
            if not session.game_over:
                # A game that just ended this very tick (ended_payload
                # above) can still have an away player whose countdown
                # reaches exactly 0 the same tick (auto-resign) -- skipping
                # this call once game_over is true is what stops that
                # stray "0s" from flashing over the GAME OVER banner;
                # there is nothing left to count down toward once the
                # game itself is decided.
                await _broadcast_countdown(registry, game_id, game_clients,
                                            current_countdown_seconds,
                                            last_countdown_seconds, dead)
        last_countdown_seconds = current_countdown_seconds
        live_game_ids = set(registry.game_ids())
        for stale_id in set(observers) - live_game_ids:
            del observers[stale_id]
            last_history_sent.pop(stale_id, None)
            last_waiting_sent.pop(stale_id, None)
        for websocket in dead:
            clients.pop(websocket, None)
