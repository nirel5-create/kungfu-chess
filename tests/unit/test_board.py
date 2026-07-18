import unittest

from model.board import Board
from model.config import Config
from tests.helpers import MoveValidator, make_game, render



class TestUnits(unittest.TestCase):
    def setUp(self):
        self.config = Config()

    def test_config_token_validation(self):
        self.assertTrue(self.config.is_valid_token("."))
        self.assertTrue(self.config.is_valid_token("wK"))
        self.assertFalse(self.config.is_valid_token("xK"))
        self.assertFalse(self.config.is_valid_token("wZ"))
        self.assertFalse(self.config.is_valid_token("wKK"))

    def test_config_same_color(self):
        self.assertTrue(self.config.same_color("wP", "wK"))
        self.assertFalse(self.config.same_color("wP", "bK"))

    def test_config_is_swappable(self):
        custom = Config(cell_size=60, colors=("g", "r"), piece_types=("D",))
        self.assertTrue(custom.is_valid_token("gD"))
        self.assertFalse(custom.is_valid_token("wK"))

    def test_board_empty_grid_dimensions(self):
        board = Board([], self.config)
        self.assertEqual(board.rows, 0)
        self.assertEqual(board.cols, 0)

    def test_board_bounds_and_piece_at(self):
        board = Board([["wP", "."]], self.config)
        self.assertTrue(board.in_bounds(0, 0))
        self.assertFalse(board.in_bounds(1, 0))
        self.assertEqual(board.piece_at(0, 0), "wP")
        self.assertIsNone(board.piece_at(0, 1))

    def test_travel_time_variant_defers_move_until_settled(self):
        class Delayed(Config):
            def travel_time(self, src, dst):
                return 100

        board = Board([["wR", "."]], self.config)
        game, ctrl = make_game(board, Delayed())
        ctrl.click(50, 50)
        ctrl.click(150, 50)
        self.assertEqual(render(board), "wR .")

    def test_default_movement_covers_KQRBN_but_not_pawn(self):
        # Rules-as-data (§9): the movement table is a config attribute.
        for piece in ("K", "Q", "R", "B", "N"):
            self.assertIn(piece, self.config.movement)
        self.assertNotIn("P", self.config.movement)

    def test_custom_direction_deltas_change_default_movement(self):
        custom = Config(orthogonal_deltas=((0, 1),))  # a rook that can only ever move right
        self.assertEqual(custom.movement["R"], [(0, 1, None, False, "any", False)])

    def test_config_movement_override(self):
        custom = Config(movement={"X": [(0, 1, 1, False, "any", None)]})
        self.assertEqual(custom.movement, {"X": [(0, 1, 1, False, "any", None)]})

    def test_travel_time_one_cell_orthogonal(self):
        self.assertEqual(self.config.travel_time((0, 0), (0, 1)), 1000)

    def test_travel_time_two_cells_diagonal_uses_step_count(self):
        self.assertEqual(self.config.travel_time((0, 0), (2, 2)), 2000)

    def test_travel_time_zero_distance(self):
        self.assertEqual(self.config.travel_time((1, 1), (1, 1)), 0)

    def test_travel_time_custom_speed(self):
        fast = Config(piece_speed_ms=250)
        self.assertEqual(fast.travel_time((0, 0), (0, 3)), 750)

    def test_is_legal_rejects_friendly_destination(self):
        # Game.click masks this via "replace selection", but the validator
        # must also reject it independently (e.g. direct API callers, future modes).
        board = Board([["wR", ".", "wP"]], self.config)
        validator = MoveValidator(board, self.config)
        # wR geometry reaches (0,2), but wP is there — must be illegal.
        self.assertFalse(validator.is_legal((0, 0), (0, 2)))

    def test_jump_ms_default_and_override(self):
        self.assertEqual(self.config.jump_ms, 1000)
        fast = Config(jump_ms=250)
        self.assertEqual(fast.jump_ms, 250)

    def test_promotion_target_white_pawn_on_far_edge(self):
        board = Board([[".", "."], [".", "."], [".", "."]], self.config)  # 3 rows
        self.assertEqual(self.config.promotion_target("wP", 0, board), "wQ")

    def test_promotion_target_black_pawn_on_far_edge(self):
        board = Board([[".", "."], [".", "."], [".", "."]], self.config)  # 3 rows
        self.assertEqual(self.config.promotion_target("bP", 2, board), "bQ")

    def test_promotion_target_none_mid_board(self):
        board = Board([[".", "."], [".", "."], [".", "."]], self.config)
        self.assertIsNone(self.config.promotion_target("wP", 1, board))

    def test_promotion_target_none_for_non_promoting_piece(self):
        board = Board([[".", "."], [".", "."], [".", "."]], self.config)
        self.assertIsNone(self.config.promotion_target("wR", 0, board))

    def test_board_set_piece_replaces_token(self):
        board = Board([["wP", "."]], self.config)
        board.set_piece((0, 0), "wQ")
        self.assertEqual(render(board), "wQ .")

    def test_is_legal_unrestricted_when_no_movement_rule_defined(self):
        # Extensibility (ctd_rules.md §5): a custom piece type with no rule
        # entry is unrestricted.
        custom = Config(piece_types=("K", "X"), movement={"K": self.config.movement["K"]})
        board = Board([["wX", "."]], custom)
        validator = MoveValidator(board, custom)
        self.assertTrue(validator.is_legal((0, 0), (0, 1)))


if __name__ == "__main__":
    unittest.main()
