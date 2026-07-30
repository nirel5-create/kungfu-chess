import numpy as np

from client.overlay import BannerOverlay


class _FakeFrame:
    def __init__(self):
        # A real (small) array, not just an object with a `.shape` --
        # draw() now writes the backing rectangle straight onto frame.img
        # with cv2.rectangle (see overlay.py's module docstring), which
        # needs an actual mutable buffer to draw into, not merely
        # something that reports a shape. put_text stays a pure spy below:
        # only the rectangle touches real pixels.
        self.img = np.zeros((100, 100, 4), dtype=np.uint8)
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
