import unittest
import pytest
from tools.fuzz_game import InvariantError, check_time_slicing, play_one





@pytest.mark.slow
class TestGameInvariants(unittest.TestCase):
    """Property test. Plays random games and asserts, after every step, the
    things that must always hold. This is what caught the ghost motion and the
    board moving after game_over -- neither is expressible as a print board
    assertion, so no VPL script could ever have found them.

    Marked slow: it is ~97% of the suite's runtime. `pytest` runs it; `pytest -m
    "not slow"` skips it and finishes in a fraction of a second, which is what
    you want while editing. Do not skip it before a commit."""

    def test_random_games_never_break_an_invariant(self):
        for seed in range(200):
            try:
                play_one(seed)
            except InvariantError as e:  # pragma: no cover - only on regression
                self.fail(f"seed {seed}: {e}")

    def test_wait_slicing_is_equivalent_across_random_games(self):
        try:
            check_time_slicing(60)
        except InvariantError as e:  # pragma: no cover - only on regression
            self.fail(str(e))


if __name__ == "__main__":
    unittest.main()
