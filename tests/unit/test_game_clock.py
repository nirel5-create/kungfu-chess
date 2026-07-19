import unittest

from input.game_clock import GameClock


class FakeEngine:
    """Records the wait() calls GameClock makes."""

    def __init__(self):
        self.waits = []

    def wait(self, ms):
        self.waits.append(ms)


class FakeTime:
    """A hand-cranked clock. `advance` moves it forward by whole seconds or
    fractions; `__call__` returns the current time in seconds."""

    def __init__(self):
        self.seconds = 0.0

    def advance(self, seconds):
        self.seconds += seconds

    def __call__(self):
        return self.seconds


class TestGameClock(unittest.TestCase):
    def setUp(self):
        self.time = FakeTime()
        self.engine = FakeEngine()
        self.clock = GameClock(self.engine, now=self.time)

    def test_a_tick_waits_the_elapsed_milliseconds(self):
        self.time.advance(0.5)                         # half a second
        waited = self.clock.tick()
        self.assertEqual(waited, 500)
        self.assertEqual(self.engine.waits, [500])

    def test_no_elapsed_time_waits_nothing(self):
        waited = self.clock.tick()                     # no advance
        self.assertEqual(waited, 0)
        self.assertEqual(self.engine.waits, [])        # engine untouched

    def test_elapsed_ms_accumulates_across_ticks(self):
        self.time.advance(0.3); self.clock.tick()
        self.time.advance(0.2); self.clock.tick()
        self.assertEqual(self.clock.elapsed_ms(), 500)

    def test_many_small_ticks_track_real_time_without_drift(self):
        # Ten 100ms ticks. Float time means a single tick may land on 99 or 100,
        # but the total must stay within 1ms of real time -- the error must not
        # accumulate. That is the property the epoch-based tick guarantees.
        for _ in range(10):
            self.time.advance(0.1)
            self.clock.tick()
        self.assertAlmostEqual(sum(self.engine.waits), 1000, delta=1)
        self.assertEqual(self.clock.elapsed_ms(), sum(self.engine.waits))

    def test_drift_does_not_grow_over_many_ticks(self):
        # After 1000 tiny ticks the total must still be within 1ms of real time.
        for _ in range(1000):
            self.time.advance(0.01)                     # 10ms each -> 10s total
            self.clock.tick()
        self.assertAlmostEqual(sum(self.engine.waits), 10000, delta=1)

    def test_a_sub_millisecond_tick_waits_nothing_and_loses_no_time(self):
        self.time.advance(0.0004)                       # 0.4 ms -> rounds to 0
        self.assertEqual(self.clock.tick(), 0)
        self.time.advance(0.0006)                       # now 1.0 ms total
        self.assertEqual(self.clock.tick(), 1)          # the held-back time appears


if __name__ == "__main__":
    unittest.main()
