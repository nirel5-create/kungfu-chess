"""The mouse callback and the per-game frame loop that opens the OpenCV
window, drives it from build_client's own parts, and closes it again once
the game ends or the player quits outright.
"""

import time

import cv2

from client import mute_button
from client.draw import (
    _MUTE_SLOT_H, _PANEL_TOP, _PANEL_WIDTH, _draw_mute_indicator,
    _draw_room_indicator, _widen_canvas,
)
from common import topics

_WINDOW = "Kung-Fu Chess (client)"


def _make_on_mouse(controller, sound_player, mute_rect_holder, mute_pressed_holder, start_time):
                    # pylint: disable=too-many-arguments, too-many-positional-arguments
                    # pylint: disable=no-member
    # cv2 is a compiled C extension, so pylint cannot introspect its members
    # -- EVENT_LBUTTONDOWN/EVENT_RBUTTONDOWN below both exist and work at
    # runtime, the same false positive _play_one_game's own disable notes.
    """-> a cv2 mouse callback (event, x, y, flags, param) closing over the
    per-game state _play_one_game builds it from, extracted out of that
    function on purpose so it can be called directly in a test with plain
    values -- on_mouse(event, x, y, None, None) -- with no real window and
    no real mouse (the mentor-suggested way to test this interface).

    A left click on the mute button's own last-drawn rect (mute_rect_holder,
    still None before the first frame -- see _play_one_game) toggles mute
    instead of reaching the controller at all; every other left click is a
    selection/move (controller.click), and a right click is always a jump
    (controller.jump) -- the same left/right split as app.py's own handler,
    just carried over a websocket instead of a local engine."""
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


def _play_one_game(controller, renderer, link, bus, banner, countdown_overlay,
                    panel, sound_player):  # pragma: no cover
    # pylint: disable=too-many-locals, too-many-statements, too-many-branches
    # pylint: disable=too-many-arguments, too-many-positional-arguments
    # pylint: disable=too-many-nested-blocks
    # One frame loop genuinely touches this many independent parts --
    # splitting it up would just move names around, the same reasoning
    # build_client's own disable gives. Statement and branch counts grew
    # the same way with the winner-banner and reconnect-message triggers,
    # the mute button's hit test, and the two ways this can end, below:
    # each is a few linear lines read once per frame, not separable
    # logic, so splitting them into their own functions would just add
    # call overhead and more names to thread the same loop-local state
    # (elapsed_ms, snapshot, mute_rect) through. The eight parameters are
    # exactly what build_client just returned plus link/sound_player --
    # one call one frame later, not a designed-in pile of unrelated
    # state. The nested-block count is `while: if snapshot: if game_over:
    # if not reported: if result:` -- each level narrows a real
    # precondition the level above it does not already rule out (a
    # snapshot to read, a game that has ended, a banner not yet queued, a
    # result actually arrived), not one flattenable decision spread
    # across several ifs.
    # cv2 is a compiled C extension, so pylint cannot introspect its
    # members: EVENT_LBUTTONDOWN, namedWindow, imshow, and the rest below
    # all exist and work at runtime (app.py, frozen and untouched, uses the
    # same members the same way). Every no-member warning from here to the
    # end of this function is that false positive, not a real one.
    # pylint: disable=no-member
    """Open the window and run one game's frame loop, from the first
    snapshot until either the player quits outright or the game ends
    naturally and its banner has finished showing. Each frame draws
    whatever snapshot the network thread last received; nothing is drawn
    before the first one.

    -> True if the player quit outright: Esc, Q, or the window's own
    close button -- client.composition.run() ends the whole client either
    way. -> False once a game ended naturally (snapshot.game_over, the
    server's own `game_over` message named a result) AND `banner` has
    finished showing it: the final position, the winner banner and the
    game-over sound all still need the window to keep drawing (and
    playing) for a moment to be seen and heard at all, so this does not
    return the instant the king falls -- it reuses BannerOverlay's own
    existing `showing` timing to know when that moment has passed, rather
    than a new bespoke timer. Either way, this function always closes the
    window itself before returning, so run() can show the home dialog
    again with nothing left over from this game's window."""
    # Populated on the first frame drawn below, once panel_x is known --
    # a click before that can only be a miss, since nothing is on screen
    # yet to hit. Plain dicts, not bare outer-scope variables: on_mouse
    # only reads/writes through these, never rebinds the names
    # themselves, so a bare variable would need `nonlocal` for no benefit
    # over a mutable container both closures already share by reference.
    mute_rect_holder = {"rect": None}
    mute_pressed_holder = {"at_ms": None}  # live-testing fix: elapsed_ms
    #   of the last click/keypress that toggled mute, or None before the
    #   first one this game -- see client/mute_button.is_pressed.

    start_time = time.time()
    on_mouse = _make_on_mouse(controller, sound_player, mute_rect_holder,
                               mute_pressed_holder, start_time)
    cv2.namedWindow(_WINDOW, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(_WINDOW, on_mouse)

    game_over_reported = False  # -> whether banner.show_result has fired
    #   for this game yet -- see the draw loop for why this is checked
    #   every frame rather than fired once on a bus event.
    previous_countdown_seconds = None  # -> link.countdown() as of the last
    #   frame, for detecting the one transition (live -> cleared, game
    #   still in progress) that actually means the opponent reconnected --
    #   see the draw loop.
    quit_outright = True
    try:
        while True:
            snapshot = link.snapshot()
            if snapshot is not None:
                # Selection is client-side view state, not game state: it is
                # this window's own idea of what is clicked, not something
                # the game rules care about. The server never sees or
                # broadcasts it -- if it did, every client would see the
                # opponent's selection, and the server would end up tracking
                # per-client UI state it has no business owning. So it is
                # stitched in here, after the fact, into the snapshot the
                # server actually sent.
                snapshot = snapshot._replace(selected_cell=controller.selection)
                elapsed_ms = int((time.time() - start_time) * 1000)
                bus.publish(topics.SNAPSHOT, snapshot)   # everyone reacts:
                #   move log, sound and the start banner all subscribe in
                #   build_client. Adding a future subscriber never touches
                #   this loop -- that is the whole justification for routing
                #   these through a bus. (Score/log now come from the
                #   server's own `history` message, not from a subscriber
                #   here -- see PanelOverlay/build_client's own comment on
                #   why. The end banner's text is decided below too, for the
                #   same reason.)
                if snapshot.game_over:
                    if not game_over_reported:
                        result = link.result()
                        # None here means the server's `game_over` message
                        # has not arrived yet -- see result()'s own
                        # docstring on why that can lag snapshot.game_over
                        # by a frame or two. Simply trying again next frame,
                        # rather than falling back to a winner-less banner
                        # now, is what makes this race harmless instead of
                        # an occasional wrong display.
                        if result is not None:
                            banner.show_result(*result)
                            game_over_reported = True
                else:
                    game_over_reported = False
                countdown_seconds = link.countdown()
                if (previous_countdown_seconds is not None and countdown_seconds is None
                        and not snapshot.game_over):
                    # The only way a live countdown goes quiet without a
                    # `game_over` message following it: the opponent's
                    # away_ms was cleared by GameRegistry.join, i.e. they
                    # reconnected. If the game ended instead (auto-resign,
                    # slide 5.2), snapshot.game_over is already true by the
                    # time this ever goes quiet -- countdown()'s own
                    # staleness window is wider than one tick, so the
                    # game-over branch above always wins that race, never
                    # this one.
                    countdown_overlay.show_reconnected(elapsed_ms)
                previous_countdown_seconds = countdown_seconds
                frame = renderer.render(snapshot, elapsed_ms)
                # Read once, before draw() consumes the same pending/expiry
                # transition -- showing() is idempotent once already
                # promoted this frame, so draw()'s own internal call below
                # sees the identical text, just without needing its own
                # return value plumbed back out here.
                banner_text = banner.showing(elapsed_ms)
                banner.draw(frame, elapsed_ms)  # centered on the true board
                #   size, before the canvas is widened below -- see
                #   _widen_canvas.
                countdown_overlay.draw(frame, countdown_seconds, elapsed_ms,
                                        waiting=link.waiting())  # same
                #   reason: drawn over the true board, not the widened panel
                #   strip.
                frame = _widen_canvas(frame, _PANEL_WIDTH)
                panel.draw(frame)
                panel_x = frame.img.shape[1] - _PANEL_WIDTH + 20
                mute_rect = mute_button.rect(panel_x, _PANEL_TOP)
                mute_rect_holder["rect"] = mute_rect
                pressed = mute_button.is_pressed(elapsed_ms, mute_pressed_holder["at_ms"])
                _draw_mute_indicator(frame, sound_player.muted, mute_rect, pressed,
                                      panel_x, _PANEL_TOP)
                _draw_room_indicator(frame, link.room(),
                                      panel_x, _PANEL_TOP + _MUTE_SLOT_H)
                cv2.imshow(_WINDOW, frame.img)
                if game_over_reported and banner_text is None:
                    # The banner's own 2-second cycle has finished: the
                    # final position and the outcome have both had their
                    # moment on screen, so this game is done -- back to
                    # home, not a break driven by any key.
                    quit_outright = False
                    break
            key = cv2.waitKey(16) & 0xFF
            # Compared case-insensitively: cv2.waitKey returns whatever
            # code the OS reports for the physical key, which is
            # upper-case while Caps Lock is on or Shift is held --
            # ord("q")/ord("m") alone then never match for the rest of the
            # session, silently, with no error and no visible symptom
            # beyond "the key does nothing" (Esc still quits, since 27 has
            # no case, so this is easy to miss entirely).
            if key in (27, ord("q"), ord("Q")):
                break
            if key in (ord("m"), ord("M")):
                sound_player.toggle_mute()
                mute_pressed_holder["at_ms"] = int((time.time() - start_time) * 1000)
            # OpenCV does not treat the window's own close ("X") button as
            # a key press -- cv2.waitKey above never sees it, so Esc/Q
            # cannot catch it. WND_PROP_VISIBLE drops below 1 the moment
            # the OS actually closes the window, which is the only signal
            # there is for that click; checked every tick, right after
            # waitKey has had its chance to pump that event.
            if cv2.getWindowProperty(_WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        cv2.destroyAllWindows()
    return quit_outright
