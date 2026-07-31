"""A short start/end banner, drawn on top of the finished frame.

Renderer is frozen, so this never draws inside it -- only over its output,
the same way ScorePanel already does.

What this module owns: a small state machine (what text is showing, and
until when) and painting that text onto a frame -- with Img.put_text for
the text itself, and a direct cv2.rectangle call on frame.img for the dark
backing behind it, since Img (frozen, view/img.py) exposes no rectangle
primitive of its own. Writing straight to frame.img is the same thing
client.py's _widen_canvas already does for the same reason (Img's public
`.img` is a plain, directly-assignable/mutable numpy array).
What it does NOT own: deciding when the game started or ended -- that is
client.events.GameEventSource -- or anything about the renderer.
"""

import cv2

# cv2 is a compiled C extension, so pylint cannot introspect its members:
# FONT_HERSHEY_SIMPLEX, getTextSize and rectangle below all exist and work
# at runtime (client.py's run() disables the same false positive for its
# own cv2 members, with the same reasoning). Every no-member warning in
# this file from here on is that false positive, not a real one.
# pylint: disable=no-member
_FONT = cv2.FONT_HERSHEY_SIMPLEX
_FONT_SIZE = 1.5
_THICKNESS = 3
_BACKING_COLOR = (0, 0, 0)  # opaque black; alpha appended below if needed
_BACKING_PADDING = 16


def _draw_with_backing(frame, text, x, y, color):
    """Paint `text` at (x, y) over a filled dark backing rectangle sized to
    it -- shared by BannerOverlay and CountdownOverlay below, since both
    need the same readable-over-any-square-color trick (see this module's
    docstring)."""
    (text_w, text_h), baseline = cv2.getTextSize(text, _FONT, _FONT_SIZE, _THICKNESS)
    channels = frame.img.shape[2]
    backing_color = _BACKING_COLOR + (255,) if channels == 4 else _BACKING_COLOR
    top_left = (x - _BACKING_PADDING, y - text_h - _BACKING_PADDING)
    bottom_right = (x + text_w + _BACKING_PADDING, y + baseline + _BACKING_PADDING)
    cv2.rectangle(frame.img, top_left, bottom_right, backing_color, thickness=-1)
    frame.put_text(text, x, y, _FONT_SIZE, color=color, thickness=_THICKNESS)


class BannerOverlay:
    """Subscribe on_game_start to topics.GAME_START and on_game_end to
    topics.GAME_END. Shows "GO" or "GAME OVER" for `duration_ms`, then
    stops.

    The state machine is kept pure and separate from drawing (see
    `showing`), so a test can assert what is showing at a given elapsed_ms
    with no frame to draw onto."""

    def __init__(self, duration_ms=2000):
        self._duration_ms = duration_ms
        self._pending = None      # text queued by on_game_start/end, not yet timestamped
        self._text = None         # currently showing, or None
        self._shown_at_ms = None  # elapsed_ms when `_text` started showing

    def on_game_start(self, payload):  # pylint: disable=unused-argument
        """Queue the start banner. `payload` is GAME_START's {} -- unused,
        kept for a uniform bus-handler signature."""
        self._pending = "GO"

    def on_game_end(self, payload):  # pylint: disable=unused-argument
        """Queue the end banner. `payload` is GAME_END's payload -- unused
        (this overlay does not report a winner), kept for the same reason
        as on_game_start."""
        self._pending = "GAME OVER"

    def showing(self, elapsed_ms):
        """-> the text that should be visible at `elapsed_ms`, or None.
        Pure: promotes a queued banner to shown (timestamping it against
        `elapsed_ms`) and expires an old one, but never touches a frame."""
        if self._pending is not None:
            self._text = self._pending
            self._shown_at_ms = elapsed_ms
            self._pending = None
        if self._text is not None and elapsed_ms - self._shown_at_ms >= self._duration_ms:
            self._text = None
        return self._text

    def draw(self, frame, elapsed_ms):
        """Draw the current banner onto `frame`, if one is showing, over a
        filled dark backing rectangle sized to the text -- without it,
        white text is unreadable over a light board square, which for
        text this size is true under roughly half of any board position.
        A no-op -- frame is never touched -- on a fresh overlay or once
        the banner has expired."""
        text = self.showing(elapsed_ms)
        if text is None:
            return
        height, width = frame.img.shape[:2]
        x, y = width // 2 - 80, height // 2
        _draw_with_backing(frame, text, x, y, color=(255, 255, 255, 255))


class CountdownOverlay:  # pylint: disable=too-few-public-methods
    """Draws the disconnect countdown (slide 5.2) over the board -- not the
    side panel, per Step 9: the opponent has vanished and the game is about
    to be decided without a move, so this must be impossible to miss.

    Reuses BannerOverlay's drawing pattern (the shared _draw_with_backing
    above) but not its state machine: a countdown is a live, externally
    updated number -- driven by _ServerLink.countdown() in client.py's run()
    -- not a one-shot announcement with a fixed duration, so there is
    nothing here to time out on its own."""

    def draw(self, frame, seconds):
        """Draw `seconds` centered near the top of the board. A no-op --
        frame untouched -- when `seconds` is None, which is how the caller
        says there is currently nothing to show (nobody away, or the away
        player just reconnected -- see _ServerLink.countdown's docstring)."""
        if seconds is None:
            return
        text = f"Opponent disconnected: {seconds}s"
        width = frame.img.shape[1]
        (text_w, _text_h), _baseline = cv2.getTextSize(text, _FONT, _FONT_SIZE, _THICKNESS)
        x, y = (width - text_w) // 2, 60
        _draw_with_backing(frame, text, x, y, color=(60, 60, 255, 255))
