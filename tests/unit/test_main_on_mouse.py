import cv2

from client.__main__ import _make_on_mouse
from client.mute_button import rect as mute_rect


class _FakeController:
    def __init__(self):
        self.clicks = []
        self.jumps = []

    def click(self, x, y):
        self.clicks.append((x, y))

    def jump(self, x, y):
        self.jumps.append((x, y))


class _FakeSoundPlayer:
    def __init__(self):
        self.mute_toggled = 0

    def toggle_mute(self):
        self.mute_toggled += 1


def _handler(mute_rect_value=None, start_time=0):
    controller = _FakeController()
    sound_player = _FakeSoundPlayer()
    mute_rect_holder = {"rect": mute_rect_value}
    mute_pressed_holder = {"at_ms": None}
    on_mouse = _make_on_mouse(controller, sound_player, mute_rect_holder,
                               mute_pressed_holder, start_time)
    return on_mouse, controller, sound_player, mute_pressed_holder


def test_left_click_calls_controller_click():
    on_mouse, controller, sound_player, _pressed = _handler()
    on_mouse(cv2.EVENT_LBUTTONDOWN, 10, 20, None, None)
    assert controller.clicks == [(10, 20)]
    assert sound_player.mute_toggled == 0


def test_right_click_calls_controller_jump():
    on_mouse, controller, sound_player, _pressed = _handler()
    on_mouse(cv2.EVENT_RBUTTONDOWN, 30, 40, None, None)
    assert controller.jumps == [(30, 40)]
    assert sound_player.mute_toggled == 0


def test_left_click_inside_the_mute_button_toggles_mute_not_the_controller():
    button_rect = mute_rect(100, 50)
    left, top, right, bottom = button_rect
    center_x, center_y = (left + right) // 2, (top + bottom) // 2
    on_mouse, controller, sound_player, pressed = _handler(mute_rect_value=button_rect)
    on_mouse(cv2.EVENT_LBUTTONDOWN, center_x, center_y, None, None)
    assert sound_player.mute_toggled == 1
    assert controller.clicks == []
    assert pressed["at_ms"] is not None


def test_left_click_outside_the_mute_button_still_reaches_the_controller():
    button_rect = mute_rect(100, 50)
    on_mouse, controller, sound_player, _pressed = _handler(mute_rect_value=button_rect)
    on_mouse(cv2.EVENT_LBUTTONDOWN, 0, 0, None, None)
    assert controller.clicks == [(0, 0)]
    assert sound_player.mute_toggled == 0


def test_a_click_before_any_frame_has_drawn_the_mute_button_is_an_ordinary_click():
    on_mouse, controller, sound_player, _pressed = _handler(mute_rect_value=None)
    on_mouse(cv2.EVENT_LBUTTONDOWN, 5, 5, None, None)
    assert controller.clicks == [(5, 5)]
    assert sound_player.mute_toggled == 0


def test_other_mouse_events_do_nothing():
    on_mouse, controller, sound_player, _pressed = _handler()
    on_mouse(cv2.EVENT_MOUSEMOVE, 1, 1, None, None)
    assert controller.clicks == []
    assert controller.jumps == []
    assert sound_player.mute_toggled == 0
