from client.overlay import BannerOverlay


class _FakeImg:
    shape = (100, 100, 4)


class _FakeFrame:
    def __init__(self):
        self.img = _FakeImg()
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
