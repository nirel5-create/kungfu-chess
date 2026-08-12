from client.link import _Connection, _CountdownState, _RoundState, _SeatOutcome


def test_connection_bundles_loop_and_thread_with_no_websocket_yet():
    loop, thread = object(), object()
    conn = _Connection(loop, thread)
    assert conn.loop is loop
    assert conn.thread is thread
    assert conn.websocket is None


def test_seat_outcome_starts_with_no_color_room_or_error():
    seat = _SeatOutcome()
    assert seat.color is None
    assert seat.room is None
    assert seat.error is None


def test_countdown_state_starts_with_no_seconds_or_timestamp():
    countdown = _CountdownState()
    assert countdown.seconds is None
    assert countdown.updated_at is None


def test_round_state_starts_fresh_across_every_field():
    state = _RoundState()
    assert state.snapshot is None
    assert state.seat.color is None
    assert state.seat.room is None
    assert state.seat.error is None
    assert state.countdown.seconds is None
    assert state.countdown.updated_at is None
    assert state.result is None
    assert state.matchmaking_status is None
    assert state.waiting is False
