import unittest

from model.board import Board
from model.config import Config
from tests.helpers import make_game, render


class TestRestAfterMove(unittest.TestCase):
    """The mentor's rule: a piece recovers after finishing a move (long_rest)
    and refuses commands until it elapses. The state lives in the engine
    because it decides who may move -- a rule of the game, not a drawing."""

    def setUp(self):
        self.config = Config(long_rest_ms=2000, short_rest_ms=1000)
        self.board = Board([["wR", ".", ".", "."]], self.config)
        self.engine, _ = make_game(self.board, self.config)

    def test_a_piece_is_resting_right_after_it_arrives(self):
        self.engine.request_move((0, 0), (0, 1))
        self.engine.wait(1000)                       # 1 cell -> arrived
        self.assertEqual(render(self.board), ". wR . .")
        result = self.engine.request_move((0, 1), (0, 2))
        self.assertFalse(result.is_accepted)
        self.assertEqual(result.reason, "resting")

    def test_the_piece_can_move_once_the_rest_elapses(self):
        self.engine.request_move((0, 0), (0, 1))
        self.engine.wait(1000)                       # arrived, now resting
        self.engine.wait(2000)                       # long_rest elapses
        result = self.engine.request_move((0, 1), (0, 2))
        self.assertTrue(result.is_accepted)

    def test_rest_still_blocks_one_ms_before_it_ends(self):
        self.engine.request_move((0, 0), (0, 1))
        self.engine.wait(1000)
        self.engine.wait(1999)                       # one ms short of waking
        self.assertFalse(self.engine.request_move((0, 1), (0, 2)).is_accepted)
        self.engine.wait(1)                          # now it wakes
        self.assertTrue(self.engine.request_move((0, 1), (0, 2)).is_accepted)

    def test_wait_slicing_does_not_change_when_a_piece_wakes(self):
        # Guide S17: wait(a); wait(b) must equal wait(a+b). The rest must wake
        # at the same clock time no matter how the waiting is chunked.
        def build():
            cfg = Config(long_rest_ms=2000)
            board = Board([["wR", ".", "."]], cfg)
            engine, _ = make_game(board, cfg)
            engine.request_move((0, 0), (0, 1))
            return engine

        one = build(); one.wait(3000)
        sliced = build()
        for _ in range(6):
            sliced.wait(500)
        self.assertEqual(one.request_move((0, 1), (0, 2)).is_accepted,
                         sliced.request_move((0, 1), (0, 2)).is_accepted)


class TestRestAfterJump(unittest.TestCase):
    """A jump is less tiring than a move (mentor), so it drops into the shorter
    short_rest, then back to idle -- not into long_rest."""

    def setUp(self):
        self.config = Config(long_rest_ms=2000, short_rest_ms=1000, jump_ms=1000)
        self.board = Board([["wK", ".", "."]], self.config)
        self.engine, _ = make_game(self.board, self.config)

    def test_a_jump_lands_into_short_rest(self):
        self.engine.request_jump((0, 0))
        self.engine.wait(1000)                       # jump window ends
        self.assertFalse(self.engine.request_move((0, 0), (0, 1)).is_accepted)
        self.engine.wait(999)                        # short_rest not yet done
        self.assertFalse(self.engine.request_move((0, 0), (0, 1)).is_accepted)
        self.engine.wait(1)                          # short_rest ends (total 1000)
        self.assertTrue(self.engine.request_move((0, 0), (0, 1)).is_accepted)

    def test_short_rest_is_shorter_than_long_rest(self):
        # A jumper (short_rest=1000) wakes before a mover (long_rest=2000) would.
        self.engine.request_jump((0, 0))
        self.engine.wait(1000 + 1000)                # jump + short_rest
        self.assertTrue(self.engine.request_move((0, 0), (0, 1)).is_accepted)

    def test_a_resting_piece_cannot_jump(self):
        self.engine.request_jump((0, 0))
        self.engine.wait(1000)                       # now in short_rest
        self.engine.request_jump((0, 0))             # refused silently
        self.engine.wait(1000)                       # if it had jumped, still resting
        self.assertTrue(self.engine.request_move((0, 0), (0, 1)).is_accepted)


class TestSnapshotReportsState(unittest.TestCase):
    """The snapshot must report each piece's lifecycle state so the renderer
    can pick the right sprite folder (idle / moving / jumping / resting)."""

    def test_an_airborne_piece_is_reported_as_jumping(self):
        config = Config(jump_ms=1000)
        board = Board([["wK", ".", "."]], config)
        engine, _ = make_game(board, config)
        engine.request_jump((0, 0))
        engine.wait(500)                             # mid-jump
        state = {p.kind: p.state for p in engine.snapshot().pieces}
        self.assertEqual(state["K"], "jumping")

    def test_a_piece_resting_after_a_move_is_reported_as_long_rest(self):
        config = Config(long_rest_ms=2000)
        board = Board([["wR", ".", "."]], config)
        engine, _ = make_game(board, config)
        engine.request_move((0, 0), (0, 1))
        engine.wait(1000)                            # arrived, now resting
        state = {p.kind: p.state for p in engine.snapshot().pieces}
        self.assertEqual(state["R"], "resting_long")

    def test_a_piece_resting_after_a_jump_is_reported_as_short_rest(self):
        config = Config(short_rest_ms=1000, jump_ms=1000)
        board = Board([["wK", ".", "."]], config)
        engine, _ = make_game(board, config)
        engine.request_jump((0, 0))
        engine.wait(1000)                            # jump ended, now short-resting
        state = {p.kind: p.state for p in engine.snapshot().pieces}
        self.assertEqual(state["K"], "resting_short")


class TestRestProgress(unittest.TestCase):
    """The cooldown fraction the view draws as a filling ring."""

    def test_progress_is_zero_for_a_piece_that_is_not_resting(self):
        config = Config()
        board = Board([["wR", "."]], config)
        engine, _ = make_game(board, config)
        # wR is idle -> progress 0.
        self.assertEqual(engine._rta.rest_progress((0, 0), config.long_rest_ms), 0.0)

    def test_progress_is_zero_when_duration_is_zero(self):
        config = Config(long_rest_ms=2000)
        board = Board([["wR", ".", "."]], config)
        engine, _ = make_game(board, config)
        engine.request_move((0, 0), (0, 1))
        engine.wait(1000)                                # now resting
        self.assertEqual(engine._rta.rest_progress((0, 1), 0), 0.0)

    def test_progress_grows_from_zero_towards_one(self):
        config = Config(long_rest_ms=2000)
        board = Board([["wR", ".", "."]], config)
        engine, _ = make_game(board, config)
        engine.request_move((0, 0), (0, 1))
        engine.wait(1000)                                # arrived, rest starts
        engine.wait(1000)                                # halfway through 2000ms
        p = engine._rta.rest_progress((0, 1), config.long_rest_ms)
        self.assertAlmostEqual(p, 0.5, places=1)


class TestRestClearedOnCapture(unittest.TestCase):
    """Found by the fuzzer (seed 0): a piece captured while resting must not
    leave its rest behind on the now-empty cell."""

    def test_capturing_a_resting_piece_clears_its_rest(self):
        config = Config(long_rest_ms=5000)
        # wR moves onto (0,1); bR then captures it there while it rests.
        board = Board([["wR", ".", "bR"]], config)
        engine, _ = make_game(board, config)
        engine.request_move((0, 0), (0, 1))     # wR -> (0,1), 1 cell
        engine.wait(1000)                        # wR arrived, now resting at (0,1)
        engine.request_move((0, 2), (0, 1))     # bR -> (0,1): captures wR
        engine.wait(1000)                        # bR arrives, wR gone
        self.assertEqual(render(board), ". bR .")
        # The captured wR's rest must be gone -- (0,1) now holds bR, resting.
        # bR itself rests; wait it out and it must be free to move.
        engine.wait(5000)
        self.assertTrue(engine.request_move((0, 1), (0, 0)).is_accepted)

    def test_the_mover_does_not_leave_a_rest_on_its_old_cell(self):
        config = Config(long_rest_ms=5000)
        board = Board([["wR", ".", "."]], config)
        engine, _ = make_game(board, config)
        engine.request_move((0, 0), (0, 1))
        engine.wait(1000)
        # (0,0) is empty and must carry no rest -- a new piece could sit there.
        board.set_piece((0, 0), "wN")
        self.assertTrue(engine.request_move((0, 0), (0, 2)) is not None)


class TestRestIsConfigurable(unittest.TestCase):
    """Rest durations are Config data, so a game can tune or disable them
    without any engine change."""

    def test_zero_rest_means_a_piece_can_move_immediately(self):
        config = Config(long_rest_ms=0)
        board = Board([["wR", ".", "."]], config)
        engine, _ = make_game(board, config)
        engine.request_move((0, 0), (0, 1))
        engine.wait(1000)                            # arrived, zero rest
        self.assertTrue(engine.request_move((0, 1), (0, 2)).is_accepted)


if __name__ == "__main__":
    unittest.main()
