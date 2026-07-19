"""Bridges wall-clock time and the engine's simulated time.

The engine knows only `wait(ms)` -- it never reads a real clock (that is what
keeps it testable and deterministic). A graphical game, though, runs in real
time: frames tick by and pieces should move accordingly. GameClock is the one
place that reads the wall clock and feeds the elapsed milliseconds to the
engine, so the engine itself stays clock-free.

The time source is injected, so a test drives it with a fake clock and asserts
the exact wait() calls -- no sleeping, no real time. The default source is the
real monotonic clock, used only by the running app.
"""

import time


class GameClock:
    def __init__(self, engine, now=None):
        """engine -- the GameEngine to advance.
        now -- a callable() -> seconds. Defaults to a monotonic wall clock;
            a test passes a fake so elapsed time is exact and instant."""
        self._engine = engine
        self._now = now if now is not None else time.monotonic
        self._epoch = self._now()
        self._last = self._epoch
        self._elapsed_ms = 0

    def elapsed_ms(self):
        """Total simulated time advanced so far -- the value the renderer uses to
        pick animation frames."""
        return self._elapsed_ms

    def tick(self):
        """Advance the engine by the real time since the last tick. Returns the
        milliseconds waited this tick. Sub-millisecond gaps are held back rather
        than rounded away, so no time is lost across many small ticks."""
        now = self._now()
        self._last = now
        elapsed_ms_float = (now - self._epoch) * 1000
        delta_ms = int(elapsed_ms_float) - self._elapsed_ms
        if delta_ms <= 0:
            return 0
        self._elapsed_ms += delta_ms
        self._engine.wait(delta_ms)
        return delta_ms
