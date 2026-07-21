import unittest

from model.board import Board
from model.config import Config
from model.snapshot import GameSnapshot, PieceView, STATE_IDLE
from tests.helpers import make_game
from view.observer import GameObserver


def _snap(tokens_at):
    """Build a snapshot from {(row, col): token}."""
    pieces = tuple(
        PieceView(t[1], t[0], r, c, c * 100, r * 100, STATE_IDLE)
        for (r, c), t in tokens_at.items()
    )
    return GameSnapshot(8, 8, 100, pieces, None, False)


class TestNamesAndInitialState(unittest.TestCase):
    def setUp(self):
        self.obs = GameObserver(Config(), white_name="Alice", black_name="Bob")

    def test_names_are_reported(self):
        self.assertEqual(self.obs.name_of("w"), "Alice")
        self.assertEqual(self.obs.name_of("b"), "Bob")

    def test_names_default_to_player_one_and_two(self):
        # Colour-neutral by default: the name stays right even if a future
        # feature lets a player pick a different piece colour.
        obs = GameObserver(Config())
        self.assertEqual(obs.name_of("w"), "Player 1")
        self.assertEqual(obs.name_of("b"), "Player 2")

    def test_scores_start_at_zero_and_log_is_empty(self):
        self.assertEqual(self.obs.score_of("w"), 0)
        self.assertEqual(self.obs.score_of("b"), 0)
        self.assertEqual(self.obs.log(), ())


class TestCaptureDetection(unittest.TestCase):
    def setUp(self):
        self.obs = GameObserver(Config())

    def test_the_first_observation_scores_nothing(self):
        self.obs.observe(_snap({(0, 0): "wR", (0, 1): "bN"}))
        self.assertEqual(self.obs.score_of("w"), 0)
        self.assertEqual(self.obs.log(), ())

    def test_a_vanished_piece_is_scored_to_the_other_side(self):
        self.obs.observe(_snap({(0, 0): "wR", (0, 1): "bN"}))
        self.obs.observe(_snap({(0, 1): "wR"}))           # wR took bN
        self.assertEqual(self.obs.score_of("w"), 3)       # knight costs 3
        self.assertEqual(self.obs.score_of("b"), 0)

    def test_a_move_without_a_capture_scores_nothing(self):
        self.obs.observe(_snap({(0, 0): "wR", (7, 7): "bK"}))
        self.obs.observe(_snap({(0, 3): "wR", (7, 7): "bK"}))  # wR just moved
        self.assertEqual(self.obs.score_of("w"), 0)
        self.assertEqual(self.obs.log(), ())

    def test_the_log_records_each_capture(self):
        self.obs.observe(_snap({(0, 0): "wR", (0, 1): "bQ"}))
        self.obs.observe(_snap({(0, 1): "wR"}), clock_ms=1500)
        log = self.obs.log()
        self.assertEqual(len(log), 1)
        entry = log[0]
        self.assertEqual(entry.capturer_color, "w")
        self.assertEqual(entry.victim_token, "bQ")
        self.assertEqual(entry.cost, 9)
        self.assertEqual(entry.clock_ms, 1500)

    def test_scores_accumulate_over_several_captures(self):
        self.obs.observe(_snap({(0, 0): "wR", (0, 1): "bP", (5, 5): "bP"}))
        self.obs.observe(_snap({(0, 1): "wR", (5, 5): "bP"}))   # took a pawn
        self.obs.observe(_snap({(5, 5): "wR"}))                 # took another
        self.assertEqual(self.obs.score_of("w"), 2)            # 1 + 1

    def test_both_sides_can_score(self):
        self.obs.observe(_snap({(0, 0): "wR", (1, 1): "bR"}))
        self.obs.observe(_snap({(0, 0): "wR"}))            # black's rook gone
        self.obs.observe(_snap({(1, 1): "bR"}))            # white's rook gone
        self.assertEqual(self.obs.score_of("w"), 5)
        self.assertEqual(self.obs.score_of("b"), 5)

    def test_the_log_is_immutable_from_outside(self):
        self.obs.observe(_snap({(0, 0): "wR", (0, 1): "bN"}))
        self.obs.observe(_snap({(0, 1): "wR"}))
        self.assertIsInstance(self.obs.log(), tuple)


class TestObserverOnRealGame(unittest.TestCase):
    """The observer must work off real engine snapshots, never touching the
    engine's move logic -- the whole point the mentor made."""

    def test_a_real_capture_is_scored_from_snapshots_alone(self):
        config = Config()
        board = Board([["wR", "bN"]], config)
        engine, _ = make_game(board, config)
        obs = GameObserver(config)

        obs.observe(engine.snapshot(), 0)                 # before
        engine.request_move((0, 0), (0, 1))               # wR -> bN
        engine.wait(config.piece_speed_ms)                # arrives, captures
        obs.observe(engine.snapshot(), config.piece_speed_ms)

        self.assertEqual(obs.score_of("w"), 3)            # knight taken
        self.assertEqual(len(obs.log()), 1)


if __name__ == "__main__":
    unittest.main()
