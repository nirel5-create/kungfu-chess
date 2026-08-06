from client.mute_button import is_hit, is_pressed, rect


def test_a_click_inside_the_buttons_rectangle_registers_as_a_hit():
    button_rect = rect(100, 50)
    left, top, right, bottom = button_rect
    center_x = (left + right) // 2
    center_y = (top + bottom) // 2
    assert is_hit(center_x, center_y, button_rect) is True


def test_a_click_outside_the_buttons_rectangle_does_not_register():
    button_rect = rect(100, 50)
    _left, top, _right, _bottom = button_rect
    assert is_hit(0, 0, button_rect) is False
    assert is_hit(100, top - 100, button_rect) is False


def test_a_click_exactly_on_the_edge_registers_as_a_hit():
    button_rect = rect(100, 50)
    left, top, right, bottom = button_rect
    assert is_hit(left, top, button_rect) is True
    assert is_hit(right, bottom, button_rect) is True


def test_the_hit_test_respects_the_panels_actual_position_not_a_hardcoded_one():
    # A click that hits the button at one panel position must NOT hit it
    # at a very different position -- the rect has to move with (x, y),
    # not stay fixed.
    near_origin = rect(10, 10)
    far_away = rect(900, 700)
    assert is_hit(15, 12, near_origin) is True
    assert is_hit(15, 12, far_away) is False
    assert is_hit(905, 702, far_away) is True
    assert is_hit(905, 702, near_origin) is False


# --- is_pressed (live-testing fix: a visible pressed flash on click) -------

def test_never_pressed_is_not_pressed():
    assert is_pressed(1000, None) is False


def test_pressed_immediately_after_the_click_is_pressed():
    assert is_pressed(1000, 1000) is True


def test_pressed_stays_pressed_just_before_the_window_expires():
    assert is_pressed(1149, 1000) is True


def test_pressed_stops_once_the_window_expires():
    assert is_pressed(1150, 1000) is False
