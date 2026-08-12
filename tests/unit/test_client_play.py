from client.play import _FrameState


def test_frame_state_starts_with_no_banner_reported_and_no_countdown_seen():
    mute_rect_holder = {"rect": None}
    mute_pressed_holder = {"at_ms": None}
    state = _FrameState(1000, mute_rect_holder, mute_pressed_holder)
    assert state.start_time == 1000
    assert state.game_over_reported is False
    assert state.previous_countdown_seconds is None
    assert state.mute_rect_holder is mute_rect_holder
    assert state.mute_pressed_holder is mute_pressed_holder
