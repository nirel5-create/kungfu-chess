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

    def show_result(self, winner, winner_username):
        """Queue the end banner naming the actual outcome: "<username>
        wins" for a decisive game, or "Game ended with no result" when
        `winner` is None -- both players disconnected (slide 5.2), or any
        other reason no result could be determined. Never "draw":
        Server_Design.md's rule is that an inconclusive game is not scored
        as one, and the banner should not suggest otherwise either.

        Separate from on_game_end (kept exactly as it was, for whatever
        wants the plain, uninformative trigger) because this needs the
        actual outcome, which only the server knows and reports by
        `winner_username`, not by color -- a color means nothing to a
        player who does not track them, but everyone knows their own
        name. See client.py's run() for when this is called instead of
        on_game_end: once game_over is true AND the server's own
        `game_over` message has actually arrived (_ServerLink.result()),
        rather than guessing from the snapshot alone."""
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


_RECONNECTED_TEXT = "Opponent reconnected"
_WAITING_TEXT = "Waiting for an opponent..."
_RECONNECTED_MS = 2000  # how long the reconnect confirmation stays up
_COUNTDOWN_COLOR = (60, 60, 255, 255)   # red-ish: something is wrong
_RECONNECTED_COLOR = (80, 200, 80, 255)  # green-ish: good news, unlike the countdown
_WAITING_COLOR = (60, 60, 255, 255)  # same red-ish as the countdown: nothing can happen yet either


class CountdownOverlay:
    """Draws connection/opponent-status text over the board -- not the
    side panel, per Step 9: the opponent may or may not still be there
    (or may not have joined at all yet, live-testing's own addition), so
    none of the messages this class shows should be easy to miss.

    Reuses BannerOverlay's drawing pattern (the shared _draw_with_backing
    above) but not its bus-driven state machine. The countdown itself
    (draw's `seconds`) is a live, externally updated number -- driven by
    _ServerLink.countdown() in client.py's run() -- not a one-shot
    announcement with a fixed duration. The reconnect confirmation IS
    timed, but on a plain elapsed_ms deadline set by show_reconnected(),
    not a bus event: run() is what notices a countdown has gone quiet
    while the game is still in progress (the one case that actually means
    the opponent came back -- see show_reconnected's own docstring), and
    this class only ever draws what it is told."""

    def __init__(self):
        self._reconnected_shown_at_ms = None  # None until show_reconnected() -- see its docstring

    def show_reconnected(self, elapsed_ms):
        """Queue the "Opponent reconnected" confirmation, starting now (in
        the same wall-clock stopwatch draw() is timed against). Call this
        only when a countdown that WAS running has gone quiet while the
        game is still in progress -- the one case that actually means the
        opponent came back, as opposed to the countdown expiring and
        ending the game instead (auto-resign, slide 5.2), which reports
        its own outcome through BannerOverlay.show_result instead. Telling
        the two apart is run()'s job, not this class's: it is the one
        place that already sees both the countdown and the snapshot's own
        game_over flag every frame."""
        self._reconnected_shown_at_ms = elapsed_ms

    def draw(self, frame, seconds, elapsed_ms, waiting=False):
        """Draw "Waiting for an opponent..." if `waiting` is True (live-
        testing fix: a game with an empty seat must say so, not just look
        frozen -- see server.py's own module docstring for the exploit
        this closes). Otherwise, draw the live countdown if one is
        running (`seconds` is not None), or "Opponent reconnected" if
        show_reconnected() was called within the last _RECONNECTED_MS of
        `elapsed_ms`. A no-op -- frame untouched -- when none apply.

        `waiting` takes priority over everything else: a game with an
        empty seat has no opponent to disconnect or reconnect in the
        first place, so the other two can only be stale leftovers from a
        PREVIOUS round on this same reused connection (Step 12) while
        `waiting` is true. Once `waiting` is false, a fresh disconnect
        still takes priority over a still-showing reconnect confirmation,
        as before: `seconds` reflects what is actually happening right
        now, which matters more than a message about what just finished
        happening."""
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
