"""Small drawing helpers the frame loop (client.play) calls once per frame:
widening the canvas for the side panel, and the mute/room indicators drawn
into that panel strip.
"""

from collections import namedtuple

import cv2
import numpy as np

from view.img import Img

_PANEL_WIDTH = 280  # extra canvas width for ScorePanel's text and the mute
#                     indicator; wide enough by eye against real frames.
_PANEL_LINE_H = 26  # matches view.score_panel's own _LINE_H (frozen and
#                     private to that module, so restated here rather
#                     than imported) -- the line rhythm for every
#                     plain-text line below the mute button's slot.
_PANEL_TOP = 30  # y (text baseline) of the mute button's own line -- tall
#                  enough that its padded border box (client/mute_button.
#                  rect: _TEXT_HEIGHT + 2*_PADDING = 32px above this
#                  baseline) fits entirely on the canvas.
_MUTE_SLOT_H = 40  # the mute button's own padded slot height -- bigger
#                    than a plain text line's _PANEL_LINE_H, since a
#                    bordered button needs padding on every side, not
#                    just room for one line of text. The room line, and
#                    everything after it, resumes the panel's ordinary
#                    _PANEL_LINE_H rhythm from here on.


def _widen_canvas(frame, extra_width):  # pragma: no cover
    """-> a new Img, `extra_width` pixels wider than `frame`, with `frame`'s
    pixels copied into the left region and a dark strip added on the
    right -- room for ScorePanel's text and the mute indicator, which sit
    past board.png's own right edge and so are off-canvas without it."""
    height, width, channels = frame.img.shape
    background = (30, 30, 30, 255) if channels == 4 else (30, 30, 30)
    canvas = np.empty((height, width + extra_width, channels), dtype=frame.img.dtype)
    canvas[:] = background
    canvas[:, :width] = frame.img
    widened = Img()
    widened.img = canvas
    return widened


_ButtonVisual = namedtuple("_ButtonVisual", "rect pressed")
# A one-shot value built fresh each frame for a single _draw_mute_indicator
# call -- not the same thing as client.play's mute_rect_holder/
# mute_pressed_holder dicts, which persist across frames and keep their
# plain-dict shape because tests/unit/test_main_on_mouse.py constructs and
# passes them positionally into _make_on_mouse, pinning that signature.


def _draw_mute_indicator(frame, muted, button, pos):  # pragma: no cover
                          # pylint: disable=no-member
    # cv2.rectangle is a compiled C extension member pylint cannot
    # introspect -- the same false positive other disables in this file
    # note.
    """Show whether sound is on or off, and the key that toggles it -- 'm'
    is otherwise undiscoverable. Also draws `button.rect` as a visible
    bordered box, with a brief highlighted fill while `button.pressed` is
    True, so the control looks clickable rather than like plain status
    text. `pos` is the (x, y) baseline to draw the status text at."""
    left, top, right, bottom = button.rect
    x, y = pos
    channels = frame.img.shape[2]
    white = (255, 255, 255, 255) if channels == 4 else (255, 255, 255)
    if button.pressed:
        highlight = (90, 90, 90, 255) if channels == 4 else (90, 90, 90)
        cv2.rectangle(frame.img, (left, top), (right, bottom), highlight, thickness=-1)
    cv2.rectangle(frame.img, (left, top), (right, bottom), white, thickness=1)
    text = "Sound: OFF (m)" if muted else "Sound: ON (m)"
    frame.put_text(text, x, y, 0.6, color=(255, 255, 255, 255))


def _draw_room_indicator(frame, room_id, x, y):  # pragma: no cover
    """Show the room id at the top of the screen, so the player (and
    anyone they read the id out to) can see which room they are in. A
    no-op when `room_id` is None: Play's ordinary shared game has no
    room to show."""
    if room_id is None:
        return
    frame.put_text(f"Room: {room_id}", x, y, 0.6, color=(255, 255, 255, 255))
