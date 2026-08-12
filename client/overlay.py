"""A start/end banner and connection-status overlay, drawn on top of the
finished frame rather than by the frozen Renderer itself.

Text needs a solid backing rectangle to stay readable over any board
square color, and Img (frozen) exposes no rectangle primitive of its
own, so this module writes straight to frame.img (a plain, mutable numpy
array) with cv2.rectangle, then layers text over it with Img.put_text.

This owns the state machine (what text is showing, and until when) and
painting it -- not deciding when the game started or ended, which is
client.events.GameEventSource's job.
"""

import cv2

# cv2 is a compiled C extension, so pylint cannot introspect its members:
# FONT_HERSHEY_SIMPLEX, getTextSize and rectangle below all exist and work
# at runtime. Every no-member warning in this file from here on is that
# false positive, not a real one.
# pylint: disable=no-member
_FONT = cv2.FONT_HERSHEY_SIMPLEX
_FONT_SIZE = 1.5
_THICKNESS = 3
_BACKING_COLOR = (0, 0, 0)  # opaque black; alpha appended below if needed
_BACKING_PADDING = 16


def _draw_with_backing(frame, text, x, y, color):
    """Paint `text` at (x, y) over a filled dark backing rectangle sized
    to it, so it stays readable over any board square color. Shared by
    BannerOverlay and CountdownOverlay below."""
    (text_w, text_h), baseline = cv2.getTextSize(text, _FONT, _FONT_SIZE, _THICKNESS)
    channels = frame.img.shape[2]
    backing_color = _BACKING_COLOR + (255,) if channels == 4 else _BACKING_COLOR
    top_left = (x - _BACKING_PADDING, y - text_h - _BACKING_PADDING)
    bottom_right = (x + text_w + _BACKING_PADDING, y + baseline + _BACKING_PADDING)
    cv2.rectangle(frame.img, top_left, bottom_right, backing_color, thickness=-1)
    frame.put_text(text, x, y, _FONT_SIZE, color=color, thickness=_THICKNESS)


class BannerOverlay:
    """Subscribes on_game_start/on_game_end to GAME_START/GAME_END.
    Shows "GO" or "GAME OVER" for `duration_ms`, then stops.

    The state machine (`showing`) is kept pure and separate from
    drawing, so a test can assert what is showing at a given elapsed_ms."""

    def __init__(self, duration_ms=2000):
        self._duration_ms = duration_ms
        self._pending = None      # text queued by on_game_start/end, not yet timestamped
        self._text = None         # currently showing, or None
        self._shown_at_ms = None  # elapsed_ms when `_text` started showing

    def on_game_start(self, payload):  # pylint: disable=unused-argument
        """Queue the start banner. `payload` (GAME_START's {}) is unused,
        kept for a uniform bus-handler signature."""
        self._pending = "GO"

    def on_game_end(self, payload):  # pylint: disable=unused-argument
        """Queue the end banner. `payload` is unused -- this overlay does
        not report a winner -- kept for the same reason as on_game_start."""
        self._pending = "GAME OVER"

    def show_result(self, winner, winner_username):
        """Queue the end banner naming the actual outcome: "<username>
        wins", or "Game ended with no result" when `winner` is None --
        never "draw", since an inconclusive game is not scored as one.
        Separate from on_game_end because this needs the actual outcome
        and the winner's name, which only the server reports."""
        if winner is None:
            self._pending = "Game ended with no result"
        else:
            self._pending = f"{winner_username} wins"

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
        """Draw the current banner onto `frame`, over a dark backing
        rectangle sized to the text, since light text is unreadable over
        a light board square. No-op if nothing is showing."""
        text = self.showing(elapsed_ms)
        if text is None:
            return
        height, width = frame.img.shape[:2]
        x, y = width // 2 - 80, height // 2
        _draw_with_backing(frame, text, x, y, color=(255, 255, 255, 255))


_RECONNECTED_TEXT = "Opponent reconnected"
_WAITING_TEXT = "Waiting for an opponent..."
_RECONNECTED_MS = 2000  # how long the reconnect confirmation stays up
_COUNTDOWN_COLOR = (60, 60, 255, 255)   # red-ish: something is wrong
_RECONNECTED_COLOR = (80, 200, 80, 255)  # green-ish: good news, unlike the countdown
_WAITING_COLOR = (60, 60, 255, 255)  # same red-ish as the countdown: nothing can happen yet either


class CountdownOverlay:
    """Draws connection/opponent-status text over the board, not the
    side panel, so it cannot be missed even if no opponent has joined
    yet. The countdown is a live, externally driven number, unlike
    BannerOverlay's one-shot bus events; the reconnect confirmation is a
    one-shot timed message set by show_reconnected()."""

    def __init__(self):
        self._reconnected_shown_at_ms = None  # None until show_reconnected() sets it

    def show_reconnected(self, elapsed_ms):
        """Queue the "Opponent reconnected" confirmation, timestamped at
        `elapsed_ms`. Call only when a countdown that was running has
        gone quiet while the game is still in progress -- as opposed to
        expiring and ending the game, which reports its own outcome
        through BannerOverlay.show_result instead."""
        self._reconnected_shown_at_ms = elapsed_ms

    def draw(self, frame, seconds, elapsed_ms, waiting=False):
        """Draw "Waiting for an opponent..." if `waiting`, else the live
        countdown if one is running, else "Opponent reconnected" if
        show_reconnected() fired within the last _RECONNECTED_MS. No-op
        if none apply. `waiting` takes priority: an empty seat has no
        opponent to disconnect or reconnect from."""
        if waiting:
            self._draw_centered(frame, _WAITING_TEXT, _WAITING_COLOR)
            return
        if seconds is not None:
            self._draw_centered(frame, f"Opponent disconnected: {seconds}s", _COUNTDOWN_COLOR)
            return
        if (self._reconnected_shown_at_ms is not None
                and elapsed_ms - self._reconnected_shown_at_ms < _RECONNECTED_MS):
            self._draw_centered(frame, _RECONNECTED_TEXT, _RECONNECTED_COLOR)

    @staticmethod
    def _draw_centered(frame, text, color):
        width = frame.img.shape[1]
        (text_w, _text_h), _baseline = cv2.getTextSize(text, _FONT, _FONT_SIZE, _THICKNESS)
        x, y = (width - text_w) // 2, 60
        _draw_with_backing(frame, text, x, y, color=color)
