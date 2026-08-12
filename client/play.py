"""The mouse callback and the per-game frame loop that opens the OpenCV
window, drives it from build_client's own parts, and closes it again once
the game ends or the player quits outright.
"""

import time

import cv2

from client import mute_button
from client.draw import (
    _MUTE_SLOT_H, _PANEL_TOP, _PANEL_WIDTH, _ButtonVisual, _draw_mute_indicator,
    _draw_room_indicator, _widen_canvas,
)
from common import topics

_WINDOW = "Kung-Fu Chess (client)"


def _make_on_mouse(controller, sound_player, mute_rect_holder, mute_pressed_holder, start_time):
                    # pylint: disable=no-member
    # cv2 is a compiled C extension, so pylint cannot introspect its members
    # -- EVENT_LBUTTONDOWN/EVENT_RBUTTONDOWN below both exist and work at
    # runtime, the same false positive _play_one_game's own disable notes.
    # This 5-parameter signature is pinned by tests/unit/test_main_on_mouse.py,
    # which constructs and passes these exact args positionally -- it cannot
    # change without changing that test.
    """-> a cv2 mouse callback (event, x, y, flags, param) closing over the
    per-game state, extracted out of _play_one_game so it can be called
    directly in a test with plain values, with no real window or mouse.
    A left click on the mute button's own last-drawn rect toggles mute
    instead of reaching the controller; a right click is always a jump."""
    def on_mouse(event, x, y, _flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN:
            rect = mute_rect_holder["rect"]
            if rect is not None and mute_button.is_hit(x, y, rect):
                sound_player.toggle_mute()
                mute_pressed_holder["at_ms"] = int((time.time() - start_time) * 1000)
                return
            controller.click(x, y)
        elif event == cv2.EVENT_RBUTTONDOWN:
            controller.jump(x, y)
    return on_mouse


class _FrameState:  # pylint: disable=too-few-public-methods
    """Everything one game's frame loop carries from one frame to the
    next: the animation stopwatch, whether the winner banner has already
    been queued for this game-over, the last-seen countdown value (for
    detecting a reconnect), and the two mute-button holders
    _make_on_mouse's pinned signature needs as plain dicts."""

    def __init__(self, start_time, mute_rect_holder, mute_pressed_holder):
        self.start_time = start_time
        self.game_over_reported = False
        self.previous_countdown_seconds = None
        self.mute_rect_holder = mute_rect_holder
        self.mute_pressed_holder = mute_pressed_holder


def _update_game_over_banner(ui, link, snapshot, state):  # pragma: no cover
    """Queue the winner banner exactly once, the first frame after both
    `snapshot.game_over` and the server's own `game_over` message
    (link.result()) have arrived -- link.result() can briefly lag, so
    simply retrying next frame instead of showing a winner-less banner
    now makes that race harmless. Resets once game_over goes false."""
    if snapshot.game_over:
        if not state.game_over_reported:
            result = link.result()
            if result is not None:
                ui.overlays.banner.show_result(*result)
                state.game_over_reported = True
    else:
        state.game_over_reported = False


def _update_countdown_overlay(ui, link, snapshot, elapsed_ms, state):  # pragma: no cover
    """-> the current countdown seconds, or None. Also queues the
    "Opponent reconnected" overlay the one time a live countdown goes
    quiet with no `game_over` following it, since a quiet countdown
    followed by game_over means auto-resign instead, not a reconnect."""
    countdown_seconds = link.countdown()
    if (state.previous_countdown_seconds is not None and countdown_seconds is None
            and not snapshot.game_over):
        ui.overlays.countdown_overlay.show_reconnected(elapsed_ms)
    state.previous_countdown_seconds = countdown_seconds
    return countdown_seconds


def _draw_one_frame(ui, link, sound_player, state, snapshot):  # pragma: no cover
                     # pylint: disable=no-member
    # cv2 is a compiled C extension, so pylint cannot introspect its
    # members: namedWindow, imshow, and the rest all exist and work at
    # runtime (app.py, frozen and untouched, uses the same members the
    # same way) -- the same false positive this module's other disables
    # note.
    """Publish `snapshot` to the bus, update the banner/countdown overlays,
    render and draw one full frame (board, overlays, widened side panel,
    mute/room indicators), and show it. -> True once the game has ended
    naturally AND the banner has finished showing it -- the caller's
    signal to stop the loop."""
    snapshot = snapshot._replace(selected_cell=ui.controller.selection)
    # Selection is client-side view state, not game state: this window's
    # own idea of what is clicked, not something game rules care about,
    # so the server never sees or broadcasts it. Stitched in here instead,
    # after the fact, into the snapshot the server actually sent.
    elapsed_ms = int((time.time() - state.start_time) * 1000)
    ui.bus.publish(topics.SNAPSHOT, snapshot)  # sound and the start
    # banner subscribe in build_client; the end banner's text is decided
    # in _update_game_over_banner instead, and score/log come from the
    # server's own `history` message, not a subscriber here.
    _update_game_over_banner(ui, link, snapshot, state)
    countdown_seconds = _update_countdown_overlay(ui, link, snapshot, elapsed_ms, state)
    frame = ui.renderer.render(snapshot, elapsed_ms)
    # Read once, before draw() consumes the same pending/expiry
    # transition -- showing() is idempotent once already promoted this
    # frame, so draw()'s own internal call below sees the identical
    # text, just without needing its own return value plumbed back out.
    banner_text = ui.overlays.banner.showing(elapsed_ms)
    ui.overlays.banner.draw(frame, elapsed_ms)  # centered on the true
    #   board size, before the canvas is widened below -- see
    #   _widen_canvas.
    ui.overlays.countdown_overlay.draw(frame, countdown_seconds, elapsed_ms,
                                        waiting=link.waiting())  # same
    #   reason: drawn over the true board, not the widened panel strip.
    frame = _widen_canvas(frame, _PANEL_WIDTH)
    ui.panel.draw(frame)
    panel_x = frame.img.shape[1] - _PANEL_WIDTH + 20
    mute_rect = mute_button.rect(panel_x, _PANEL_TOP)
    state.mute_rect_holder["rect"] = mute_rect
    pressed = mute_button.is_pressed(elapsed_ms, state.mute_pressed_holder["at_ms"])
    _draw_mute_indicator(frame, sound_player.muted, _ButtonVisual(mute_rect, pressed),
                          (panel_x, _PANEL_TOP))
    _draw_room_indicator(frame, link.room(), panel_x, _PANEL_TOP + _MUTE_SLOT_H)
    cv2.imshow(_WINDOW, frame.img)
    return state.game_over_reported and banner_text is None


def _handle_input(sound_player, state):  # pragma: no cover
    # pylint: disable=no-member
    # cv2 is a compiled C extension, so pylint cannot introspect
    # waitKey/getWindowProperty/WND_PROP_VISIBLE -- the same false
    # positive this module's other disables note.
    """Read and act on one key or window-close event. -> True if the game
    window should close now: Esc, Q (checked case-insensitively, since
    Caps Lock or Shift makes the OS report an upper-case code), or the
    window's own close ("X") button -- not a key press, so it's detected
    via WND_PROP_VISIBLE instead. 'm'/'M' toggles mute without closing."""
    key = cv2.waitKey(16) & 0xFF
    if key in (27, ord("q"), ord("Q")):
        return True
    if key in (ord("m"), ord("M")):
        sound_player.toggle_mute()
        state.mute_pressed_holder["at_ms"] = int((time.time() - state.start_time) * 1000)
    return cv2.getWindowProperty(_WINDOW, cv2.WND_PROP_VISIBLE) < 1


def _play_one_game(ui, link, sound_player):  # pragma: no cover
    """Open the window and run one game's frame loop until the player
    quits outright or the game ends naturally and its banner has finished
    showing -- reusing BannerOverlay's own `showing` timing so the final
    position and outcome stay on screen for a moment instead of vanishing
    the instant the king falls. Always closes the window before returning."""
    # Populated on the first frame drawn below, once panel_x is known --
    # a click before that can only be a miss, since nothing is on screen
    # yet to hit. Plain dicts rather than bare outer-scope variables:
    # on_mouse only reads/writes through these, never rebinds the names,
    # so a shared mutable container works with no `nonlocal` needed.
    mute_rect_holder = {"rect": None}
    # elapsed_ms of the last click/keypress that toggled mute, or None
    # before the first one this game.
    mute_pressed_holder = {"at_ms": None}
    state = _FrameState(time.time(), mute_rect_holder, mute_pressed_holder)

    on_mouse = _make_on_mouse(ui.controller, sound_player, mute_rect_holder,
                               mute_pressed_holder, state.start_time)
    cv2.namedWindow(_WINDOW, cv2.WINDOW_AUTOSIZE)  # pylint: disable=no-member
    cv2.setMouseCallback(_WINDOW, on_mouse)  # pylint: disable=no-member

    quit_outright = True
    try:
        while True:
            snapshot = link.snapshot()
            if snapshot is not None and _draw_one_frame(ui, link, sound_player, state, snapshot):
                # The banner's own 2-second cycle has finished: the final
                # position and the outcome have both had their moment on
                # screen, so this game is done -- back to home, not a
                # break driven by any key.
                quit_outright = False
                break
            if _handle_input(sound_player, state):
                break
    finally:
        cv2.destroyAllWindows()  # pylint: disable=no-member
    return quit_outright
