"""A short start/end banner, drawn on top of the finished frame.

Renderer is frozen, so this never draws inside it -- only over its output,
the same way ScorePanel already does.

What this module owns: a small state machine (what text is showing, and
until when) and painting that text onto a frame with Img.put_text, which
already exists.
What it does NOT own: deciding when the game started or ended -- that is
client.events.GameEventSource -- or anything about the renderer.
"""


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
        """Draw the current banner onto `frame`, if one is showing. A
        no-op -- frame is never touched -- on a fresh overlay or once the
        banner has expired."""
        text = self.showing(elapsed_ms)
        if text is None:
            return
        height, width = frame.img.shape[:2]
        frame.put_text(text, width // 2 - 80, height // 2, 1.5,
                        color=(255, 255, 255, 255), thickness=3)
