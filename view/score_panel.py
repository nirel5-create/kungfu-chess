"""Turns the observer's state into on-screen text: player names, scores, and a
moves log.

The layout -- what each line says and where it sits -- is pure and testable. The
only part that touches the image library is draw(), which walks the computed
lines and calls put_text for each. So the wording and positions can be asserted
with no window.

The panel reads from a GameObserver; it never reads the engine. That keeps the
mentor's separation intact: the board's move logic and this side panel do not
know about each other.
"""

from collections import namedtuple

TextLine = namedtuple("TextLine", "text x y")

_HEADER_SIZE = 0.9
_ENTRY_SIZE = 0.6
_LINE_H = 26
_MAX_LOG_LINES = 12


class ScorePanel:
    def __init__(self, observer, x, y):
        """observer -- the GameObserver to read.
        x, y -- top-left pixel where the panel starts."""
        self._observer = observer
        self._x = x
        self._y = y

    def lines(self):
        """The text lines to draw, as TextLine(text, x, y). Newest log entries
        are shown; older ones scroll off so the panel stays a fixed height."""
        out = []
        y = self._y
        for color in ("w", "b"):
            name = self._observer.name_of(color)
            score = self._observer.score_of(color)
            out.append(TextLine(f"{name}: {score}", self._x, y))
            y += _LINE_H

        y += _LINE_H // 2
        recent = self._observer.log()[-_MAX_LOG_LINES:]
        for entry in recent:
            capturer = self._observer.name_of(entry.capturer_color)
            out.append(TextLine(
                f"{capturer} took {entry.victim_token} (+{entry.cost})",
                self._x, y))
            y += _LINE_H
        return out

    def draw(self, image, header_color=(255, 255, 255, 255)):
        """Paint every line onto the image. The one method that needs the image
        library; the header lines (the two scores) are drawn larger."""
        computed = self.lines()
        for i, line in enumerate(computed):
            size = _HEADER_SIZE if i < 2 else _ENTRY_SIZE
            image.put_text(line.text, line.x, line.y, size, color=header_color)
        return image
