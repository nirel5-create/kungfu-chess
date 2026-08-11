"""Small drawing helpers the frame loop (client.play) calls once per frame:
widening the canvas for the side panel, and the mute/room indicators drawn
into that panel strip.
"""

import cv2
import numpy as np

from view.img import Img

_PANEL_WIDTH = 280  # extra canvas width for ScorePanel's text and the mute
#                     indicator; wide enough by eye against real rendered
#                     frames (see the manual verification for this fix).
_PANEL_LINE_H = 26  # matches view.score_panel's own _LINE_H (frozen,
#                     private to that module, so restated here rather than
#                     imported) -- the ordinary line rhythm for every
#                     plain-text line below the mute button's own slot
#                     (room, then ScorePanel's own content), and what
#                     keeps them from overlapping each other.
_PANEL_TOP = 30  # y (text baseline) of the mute button's own line -- tall
#                  enough that its padded border box (client/mute_button.
#                  rect: _TEXT_HEIGHT + 2*_PADDING = 32px above this
#                  baseline) fits entirely on the canvas instead of
#                  running off the top edge (live-testing fix: it used to
#                  start at 15, which clipped the box's own top).
_MUTE_SLOT_H = 40  # the mute button's own padded slot height -- bigger
#                    than a plain text line's _PANEL_LINE_H, since a
#                    bordered button needs padding on every side, not
#                    just room for one line of text (live-testing fix:
#                    the room line used to sit right at _PANEL_LINE_H
#                    below the button, cramped against its padded box).
#                    The room line, and everything after it, resumes the
#                    panel's ordinary _PANEL_LINE_H rhythm from here on.


def _widen_canvas(frame, extra_width):  # pragma: no cover
    """-> a new Img, `extra_width` pixels wider than `frame`, with `frame`'s
    pixels copied into the left region and a dark strip added on the right
    -- room for ScorePanel's text and the mute indicator, which app.py never
    had: board.png is 816px wide and ScorePanel is placed at
    x=image_w+20=836, off the canvas entirely. That is true in app.py too,
    so the panel has never been visible there either -- fixed here only,
    since app.py and view/ are frozen."""
    height, width, channels = frame.img.shape
    background = (30, 30, 30, 255) if channels == 4 else (30, 30, 30)
    canvas = np.empty((height, width + extra_width, channels), dtype=frame.img.dtype)
    canvas[:] = background
    canvas[:, :width] = frame.img
    widened = Img()
    widened.img = canvas
    return widened


def _draw_mute_indicator(frame, muted, button_rect, pressed, x, y):  # pragma: no cover
                          # pylint: disable=too-many-arguments, too-many-positional-arguments
                          # pylint: disable=no-member
    # Five independent pieces this one small draw needs (mute state, the
    # button's own geometry and press state, and where to draw) -- the
    # same reasoning other disables in this file give. cv2.rectangle is a
    # compiled C extension member pylint cannot introspect.
    """Show whether sound is on or off, and the key that toggles it -- 'm'
    is otherwise undiscoverable. Also draws `button_rect` (client/
    mute_button.rect) as a visible bordered box, with a brief highlighted
    fill while `pressed` (client/mute_button.is_pressed) is True -- fixed
    by live testing: the control worked when clicked but looked like
    plain status text, with nothing to suggest it was clickable at all.

    The rectangle is drawn straight onto frame.img with cv2.rectangle,
    the same pattern this module's own _widen_canvas and client/overlay.
    py's _draw_with_backing already use for the same reason: Img (frozen)
    exposes no rectangle primitive of its own."""
    left, top, right, bottom = button_rect
    channels = frame.img.shape[2]
    white = (255, 255, 255, 255) if channels == 4 else (255, 255, 255)
    if pressed:
        highlight = (90, 90, 90, 255) if channels == 4 else (90, 90, 90)
        cv2.rectangle(frame.img, (left, top), (right, bottom), highlight, thickness=-1)
    cv2.rectangle(frame.img, (left, top), (right, bottom), white, thickness=1)
    text = "Sound: OFF (m)" if muted else "Sound: ON (m)"
    frame.put_text(text, x, y, 0.6, color=(255, 255, 255, 255))


def _draw_room_indicator(frame, room_id, x, y):  # pragma: no cover
    """Show the room id at the top of the screen -- slide 6 requires this
    for both Create and Join, so the player (and anyone they read the id
    out to) can see which room they are in. A no-op when `room_id` is
    None: Play's ordinary shared game has no room to show."""
    if room_id is None:
        return
    frame.put_text(f"Room: {room_id}", x, y, 0.6, color=(255, 255, 255, 255))
