"""The clickable mute button drawn in the panel strip. A keyboard
shortcut ('m') and this button are the same action, reachable two ways,
not alternatives.

Pure rectangle geometry and a pure hit test, taking plain numbers rather
than an Img or a cv2 handle, so both are testable with no window and no
cv2 import. _TEXT_WIDTH/_TEXT_HEIGHT are cv2.getTextSize's own
measurement for "Sound: OFF (m)" (the longer of the two states, so the
box never resizes when the state toggles), restated here as constants
rather than importing cv2 into this otherwise window-free module.

rect() pads around the text rather than sitting flush against it: flush
padding used to clip the box off-canvas on top and crop the leftmost
glyph against the border.
"""

_TEXT_WIDTH = 130   # cv2.getTextSize("Sound: OFF (m)", FONT_HERSHEY_SIMPLEX,
#                     0.6, 1) measures 128px wide; a couple of px to spare.
_TEXT_HEIGHT = 16   # same measurement's own text height (above the baseline).
_PADDING = 8   # px of breathing room around the text on every side, not
#                flush against the glyphs -- see this module's own docstring.
_PRESSED_MS = 150  # how long the pressed/highlighted look lingers after a click


def rect(x, y):
    """-> (left, top, right, bottom) for the mute button, given the same
    (x, y) the "Sound: ON/OFF (m)" text's baseline is drawn at. Padded
    by _PADDING around the text's measured footprint, and computed from
    `x, y` so the clickable area tracks wherever the panel actually is."""
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
    given it was last clicked or toggled at `pressed_at_ms`. -> False if
    `pressed_at_ms` is None (never pressed yet this game)."""
    return pressed_at_ms is not None and elapsed_ms - pressed_at_ms < _PRESSED_MS
