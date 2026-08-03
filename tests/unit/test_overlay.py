import numpy as np

from client.overlay import BannerOverlay, CountdownOverlay


class _FakeFrame:
    def __init__(self, width=100, height=100):
        # A real array, not just an object with a `.shape` -- draw() now
        # writes the backing rectangle straight onto frame.img with
        # cv2.rectangle (see overlay.py's module docstring), which needs an
        # actual mutable buffer to draw into, not merely something that
        # reports a shape. put_text stays a pure spy below: only the
        # rectangle touches real pixels. width/height default to a small
        # 100x100 (enough for BannerOverlay's short banners below); the
        # CountdownOverlay tests pass a board-sized frame instead, since
        # its longer text would not fit inside 100px.
        self.img = np.zeros((height, width, 4), dtype=np.uint8)
        self.calls = []

    def put_text(self, *args, **kwargs):
        self.calls.append((args, kwargs))


def test_nothing_shows_before_any_event():
    overlay = BannerOverlay()
    assert overlay.showing(0) is None


def test_after_on_game_start_a_banner_shows():
    overlay = BannerOverlay()
    overlay.on_game_start({})
    assert overlay.showing(0) == "GO"


def test_the_banner_stops_after_duration_ms_has_elapsed():
    overlay = BannerOverlay(duration_ms=2000)
    overlay.on_game_start({})
    assert overlay.showing(0) == "GO"
    assert overlay.showing(1999) == "GO"
    assert overlay.showing(2000) is None


def test_on_game_end_shows_its_own_banner():
    overlay = BannerOverlay()
    overlay.on_game_end({})
    assert overlay.showing(0) == "GAME OVER"


def test_draw_on_a_fresh_overlay_does_not_touch_the_frame():
    overlay = BannerOverlay()
    frame = _FakeFrame()
    overlay.draw(frame, 0)
    assert frame.calls == []


def test_draw_calls_put_text_when_a_banner_is_showing():
    overlay = BannerOverlay()
    overlay.on_game_start({})
    frame = _FakeFrame()
    overlay.draw(frame, 0)
    assert len(frame.calls) == 1


def test_draw_paints_a_dark_backing_rectangle_behind_the_text():
    # Readability fix: white banner text over a light board square used to
    # be unreadable. The backing is drawn straight onto frame.img (see
    # overlay.py's module docstring), not through put_text, so it would
    # not show up in frame.calls at all -- checked on the pixels instead.
    overlay = BannerOverlay()
    overlay.on_game_start({})
    frame = _FakeFrame()
    overlay.draw(frame, 0)
    assert frame.img.any()  # started all-zero; the backing changed pixels
    center = frame.img[50, 20]  # inside the rectangle, left of the text glyphs
    assert tuple(center[:3]) == (0, 0, 0)
    assert center[3] == 255


# --- BannerOverlay.show_result (winner by username, not color) --------------

def test_show_result_names_the_winner_by_username():
    overlay = BannerOverlay()
    overlay.show_result("w", "alice")
    assert overlay.showing(0) == "alice wins"


def test_show_result_with_no_winner_says_no_result_not_a_draw():
    overlay = BannerOverlay()
    overlay.show_result(None, None)
    assert overlay.showing(0) == "Game ended with no result"


def test_show_result_expires_after_duration_ms_like_any_other_banner():
    overlay = BannerOverlay(duration_ms=2000)
    overlay.show_result("b", "bob")
    assert overlay.showing(0) == "bob wins"
    assert overlay.showing(1999) == "bob wins"
    assert overlay.showing(2000) is None


# --- CountdownOverlay (Step 9, slide 5.2) ------------------------------------

def test_countdown_overlay_draws_nothing_when_seconds_is_none():
    overlay = CountdownOverlay()
    frame = _FakeFrame()
    overlay.draw(frame, None, 0)
    assert frame.calls == []
    assert not frame.img.any()


def test_countdown_overlay_calls_put_text_when_seconds_is_given():
    overlay = CountdownOverlay()
    frame = _FakeFrame(width=900, height=700)  # board-sized: see _FakeFrame
    overlay.draw(frame, 5, 0)
    assert len(frame.calls) == 1


def test_countdown_overlay_paints_a_backing_rectangle_behind_the_text():
    # Same readability fix as BannerOverlay's own rectangle test above,
    # reused via _draw_with_backing -- checked on the pixels since the
    # rectangle is drawn straight onto frame.img, not through put_text.
    overlay = CountdownOverlay()
    frame = _FakeFrame(width=900, height=700)
    overlay.draw(frame, 5, 0)
    center = frame.img[55, 450]  # near the vertical/horizontal center of
    #   the text's backing box -- see draw()'s x, y computation.
    assert tuple(center[:3]) == (0, 0, 0)
    assert center[3] == 255


# --- CountdownOverlay.show_reconnected ---------------------------------------

def test_reconnected_draws_nothing_if_never_shown():
    overlay = CountdownOverlay()
    frame = _FakeFrame(width=900, height=700)
    overlay.draw(frame, None, 0)
    assert frame.calls == []


def test_show_reconnected_then_draw_with_no_seconds_shows_the_confirmation():
    overlay = CountdownOverlay()
    overlay.show_reconnected(1000)
    frame = _FakeFrame(width=900, height=700)
    overlay.draw(frame, None, 1500)
    assert len(frame.calls) == 1


def test_reconnected_confirmation_expires_after_its_own_duration():
    overlay = CountdownOverlay()
    overlay.show_reconnected(1000)
    frame = _FakeFrame(width=900, height=700)
    overlay.draw(frame, None, 1000 + 2000)
    assert frame.calls == []


def test_a_fresh_countdown_takes_priority_over_a_still_showing_reconnected_message():
    overlay = CountdownOverlay()
    overlay.show_reconnected(1000)
    frame = _FakeFrame(width=900, height=700)
    overlay.draw(frame, 20, 1100)  # opponent disconnected again, quickly
    assert len(frame.calls) == 1
    (args, _kwargs) = frame.calls[0]
    assert "disconnected" in args[0]
