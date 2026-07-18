import unittest

from model.board import Board
from model.config import Config
from rules.rules import RuleEngine
from tests.helpers import make_game



class TestValidationReasons(unittest.TestCase):
    """Guide S8: reason is always present and machine-readable -- "ok" when
    valid, otherwise a stable string. Guide S9: GameEngine copies rule-level
    reasons verbatim and adds its own application-level ones."""

    def setUp(self):
        self.config = Config()
        self.board = Board([["wR", "wN", "bR"],
                            [".", ".", "."]], self.config)
        self.rules = RuleEngine(self.board, self.config)

    def test_a_valid_move_reports_ok(self):
        v = self.rules.validate_move((0, 0), (1, 0))
        self.assertTrue(v.is_valid)
        self.assertEqual(v.reason, "ok")

    def test_outside_the_board(self):
        v = self.rules.validate_move((0, 0), (9, 9))
        self.assertEqual(v.reason, "outside_board")

    def test_empty_source(self):
        v = self.rules.validate_move((1, 1), (1, 2))
        self.assertEqual(v.reason, "empty_source")

    def test_friendly_destination(self):
        v = self.rules.validate_move((0, 0), (0, 1))   # wR -> wN
        self.assertEqual(v.reason, "friendly_destination")

    def test_illegal_piece_move(self):
        v = self.rules.validate_move((0, 0), (1, 1))   # a rook cannot go diagonally
        self.assertEqual(v.reason, "illegal_piece_move")

    def test_engine_copies_the_rule_level_reason_verbatim(self):
        engine, _ = make_game(self.board, self.config)
        result = engine.request_move((0, 0), (1, 1))
        self.assertFalse(result.is_accepted)
        self.assertEqual(result.reason, "illegal_piece_move")

    def test_engine_reports_ok_for_an_accepted_command(self):
        engine, _ = make_game(self.board, self.config)
        result = engine.request_move((0, 0), (1, 0))
        self.assertTrue(result.is_accepted)
        self.assertEqual(result.reason, "ok")


if __name__ == "__main__":
    unittest.main()
