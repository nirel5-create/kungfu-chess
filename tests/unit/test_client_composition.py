from client.composition import _GameUI, _Overlays


def test_game_ui_bundles_its_parts():
    controller, renderer, bus, overlays, panel = (
        object(), object(), object(), object(), object())
    ui = _GameUI(controller, renderer, bus, overlays, panel)
    assert ui.controller is controller
    assert ui.renderer is renderer
    assert ui.bus is bus
    assert ui.overlays is overlays
    assert ui.panel is panel


def test_overlays_bundles_banner_and_countdown_overlay():
    banner, countdown_overlay = object(), object()
    overlays = _Overlays(banner, countdown_overlay)
    assert overlays.banner is banner
    assert overlays.countdown_overlay is countdown_overlay
