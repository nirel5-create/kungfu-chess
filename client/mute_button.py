"""The clickable mute button drawn in the panel strip (Step 12: "a mute
button that can be clicked" -- 'm' already toggles it, but a keyboard
shortcut and a button are the same action reachable two ways, not
alternatives).

Pure rectangle geometry and a pure hit test, kept out of client/__main__.py's
own mouse callback (client/__main__.py's _make_on_mouse is itself directly
testable -- see tests/unit/test_main_on_mouse.py -- but everything below it
in that module still opens a real window, hence still pragma: no cover).
Both functions here take plain numbers, not an Img or a cv2 handle, so they
need no window to test.

is_pressed (live-testing fix) is the same kind of pure timing decision as
client/overlay.py's BannerOverlay.showing: nothing here draws anything --
client.py's own _draw_mute_indicator does that, using this module's
`rect` for its border and `is_pressed` for its brief highlighted flash,
which is what makes the control read as something to click at all rather
than plain status text.

rect's own padding (also a live-testing fix) was originally flush against
the text's own edges on every side: with no top padding, the box's top
ran to y - 20 against a baseline as small as 15, putting it off the
canvas entirely (clipped); with no left padding, the box's left edge sat
exactly at the text's own left edge, cropping the leftmost glyph against
the border line. _TEXT_WIDTH/_TEXT_HEIGHT are cv2.getTextSize's own
measurement for "Sound: OFF (m)" (the longer of the two states, so the
box never changes size when the state toggles) at the panel's actual
font size and thickness (client.py's _draw_mute_indicator: 0.6, default
thickness 1) -- restated here as measured constants, the same way
client.py's own _PANEL_LINE_H restates view.score_panel's frozen
_LINE_H, rather than importing cv2 into this otherwise cv2-free, pure,
window-free module (see this docstring's own second paragraph)."""

_TEXT_WIDTH = 130   # cv2.getTextSize("Sound: OFF (m)", FONT_HERSHEY_SIMPLEX,
#                     0.6, 1) measures 128px wide; a couple of px to spare.
_TEXT_HEIGHT = 16   # same measurement's own text height (above the baseline).
_PADDING = 8   # px of breathing room around the text on every side, not
#                flush against the glyphs -- see this module's own docstring.
_PRESSED_MS = 150  # how long the pressed/highlighted look lingers after a click


def rect(x, y):
    """-> (left, top, right, bottom) for the mute button, given the same
    (x, y) client.py's own _draw_mute_indicator draws the "Sound: ON/OFF
    (m)" text's BASELINE at -- cv2.putText's own convention, the
    bottom-left corner of the text, not its top. Padded by _PADDING on
    every side around the text's own measured footprint (_TEXT_WIDTH x
    _TEXT_HEIGHT), so the border sits around the text rather than flush
    against it. Computing this from `x, y` rather than a hardcoded screen
    position is what keeps the clickable area tracking wherever the
    panel itself actually is, even if that position ever changes."""
    return (x - _PADDING, y - _TEXT_HEIGHT - _PADDING,
            x + _TEXT_WIDTH + _PADDING, y + _PADDING)


def is_hit(x, y, button_rect):
    """-> whether the point (x, y) -- a click, in the same pixel
    coordinates the OpenCV window reports -- falls inside `button_rect` =
    (left, top, right, bottom), inclusive of the edges."""
    left, top, right, bottom = button_rect
    return left <= x <= right and top <= y <= bottom


def is_pressed(elapsed_ms, pressed_at_ms):
    """-> whether the button should still look pressed at `elapsed_ms`,
    given it was last clicked (or, from the keyboard, last toggled) at
    `pressed_at_ms` -- the same wall-clock stopwatch client.py's own
    frame loop already times everything against. -> False if
    `pressed_at_ms` is None, i.e. never pressed yet this game (a fresh
    round -- see client.py's run() -- shows no lingering flash from a
    previous one)."""
    return pressed_at_ms is not None and elapsed_ms - pressed_at_ms < _PRESSED_MS
