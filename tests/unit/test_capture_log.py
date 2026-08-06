import unittest

from common.capture_log import CaptureLog
from model.board import Board
from model.config import Config
from model.snapshot import GameSnapshot, PieceView, STATE_IDLE
from tests.helpers import make_game


def _snap(tokens_at):
    """Build a snapshot from {(row, col): token}."""
    pieces = tuple(
        PieceView(t[1], t[0], r, c, c * 100, r * 100, STATE_IDLE)
        for (r, c), t in tokens_at.items()
    )
    return GameSnapshot(8, 8, 100, pieces, None, False)


class TestInitialState(unittest.TestCase):
    def setUp(self):
        self.log = CaptureLog(Config())

    def test_scores_start_at_zero_and_log_is_empty(self):
        self.assertEqual(self.log.score_of("w"), 0)
        self.assertEqual(self.log.score_of("b"), 0)
        self.assertEqual(self.log.log(), ())


class TestCaptureDetection(unittest.TestCase):
    def setUp(self):
        self.log = CaptureLog(Config())

    def test_the_first_observation_scores_nothing(self):
        self.log.observe(_snap({(0, 0): "wR", (0, 1): "bN"}))
        self.assertEqual(self.log.score_of("w"), 0)
        self.assertEqual(self.log.log(), ())

    def test_a_vanished_piece_is_scored_to_the_other_side(self):
        self.log.observe(_snap({(0, 0): "wR", (0, 1): "bN"}))
        self.log.observe(_snap({(0, 1): "wR"}))            # wR took bN
        self.assertEqual(self.log.score_of("w"), 3)        # knight costs 3
        self.assertEqual(self.log.score_of("b"), 0)

    def test_a_move_without_a_capture_scores_nothing(self):
        self.log.observe(_snap({(0, 0): "wR", (7, 7): "bK"}))
        self.log.observe(_snap({(0, 3): "wR", (7, 7): "bK"}))  # wR just moved
        self.assertEqual(self.log.score_of("w"), 0)
        self.assertEqual(self.log.log(), ())

    def test_the_log_records_each_capture(self):
        self.log.observe(_snap({(0, 0): "wR", (0, 1): "bQ"}))
        self.log.observe(_snap({(0, 1): "wR"}), clock_ms=1500)
        log = self.log.log()
        self.assertEqual(len(log), 1)
        entry = log[0]
        self.assertEqual(entry.capturer_color, "w")
        self.assertEqual(entry.victim_token, "bQ")
        self.assertEqual(entry.cost, 9)
        self.assertEqual(entry.clock_ms, 1500)

    def test_scores_accumulate_over_several_captures(self):
        self.log.observe(_snap({(0, 0): "wR", (0, 1): "bP", (5, 5): "bP"}))
        self.log.observe(_snap({(0, 1): "wR", (5, 5): "bP"}))   # took a pawn
        self.log.observe(_snap({(5, 5): "wR"}))                 # took another
        self.assertEqual(self.log.score_of("w"), 2)            # 1 + 1

    def test_both_sides_can_score(self):
        self.log.observe(_snap({(0, 0): "wR", (1, 1): "bR"}))
        self.log.observe(_snap({(0, 0): "wR"}))            # black's rook gone
        self.log.observe(_snap({(1, 1): "bR"}))            # white's rook gone
        self.assertEqual(self.log.score_of("w"), 5)
        self.assertEqual(self.log.score_of("b"), 5)

    def test_the_log_is_immutable_from_outside(self):
        self.log.observe(_snap({(0, 0): "wR", (0, 1): "bN"}))
        self.log.observe(_snap({(0, 1): "wR"}))
        self.assertIsInstance(self.log.log(), tuple)


class TestCaptureLogOnRealGame(unittest.TestCase):
    """CaptureLog must work off real engine snapshots, never touching the
    engine's move logic -- the same separation GameObserver keeps."""

    def test_a_real_capture_is_scored_from_snapshots_alone(self):
        config = Config()
        board = Board([["wR", "bN"]], config)
        engine, _ = make_game(board, config)
        log = CaptureLog(config)

        log.observe(engine.snapshot(), 0)                 # before
        engine.request_move((0, 0), (0, 1))               # wR -> bN
        engine.wait(config.piece_speed_ms)                # arrives, captures
        log.observe(engine.snapshot(), config.piece_speed_ms)

        self.assertEqual(log.score_of("w"), 3)            # knight taken
        self.assertEqual(len(log.log()), 1)


if __name__ == "__main__":
    unittest.main()
