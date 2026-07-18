import unittest

from model.board import Board
from model.config import Config
from rules.rules import PieceRules
from tests.helpers import MoveValidator, cell_center, render, run_fixture, wait_for



class TestMovementRules(unittest.TestCase):
    """One click selects, the next click attempts a move. Illegal moves are
    silently ignored (board unchanged)."""

    def test_king_one_step_diagonally(self):
        src_x, src_y = cell_center(0, 0)
        dst_x, dst_y = cell_center(1, 1)
        fixture = (
            "Board:\nwK . .\n. . .\n. . .\nCommands:\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(1)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". . .\n. wK .\n. . .\n")

    def test_king_two_steps_ignored(self):
        fixture = (
            "Board:\nwK . .\n. . .\n. . .\nCommands:\n"
            "click 50 50\n"
            "click 250 50\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), "wK . .\n. . .\n. . .\n")

    def test_rook_slides_along_rank(self):
        src_x, src_y = cell_center(0, 0)
        dst_x, dst_y = cell_center(3, 0)
        fixture = (
            "Board:\nwR . . .\nCommands:\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(3)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". . . wR\n")

    def test_rook_slides_along_file(self):
        src_x, src_y = cell_center(0, 0)
        dst_x, dst_y = cell_center(0, 3)
        fixture = (
            "Board:\nwR .\n. .\n. .\n. .\nCommands:\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(3)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". .\n. .\n. .\nwR .\n")

    def test_rook_diagonal_ignored(self):
        fixture = (
            "Board:\nwR .\n. .\nCommands:\n"
            "click 50 50\n"
            "click 150 150\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), "wR .\n. .\n")

    def test_rook_blocked_by_piece_on_ray(self):
        # bP at (0,2) blocks the ray to bR at (0,3).
        fixture = (
            "Board:\nwR . bP bR\nCommands:\n"
            "click 50 50\n"
            "click 350 50\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), "wR . bP bR\n")

    def test_rook_captures_at_end_of_ray(self):
        src_x, src_y = cell_center(0, 0)
        dst_x, dst_y = cell_center(3, 0)
        fixture = (
            "Board:\nwR . . bR\nCommands:\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(3)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". . . wR\n")

    def test_bishop_slides_diagonally(self):
        src_x, src_y = cell_center(0, 0)
        dst_x, dst_y = cell_center(2, 2)
        fixture = (
            "Board:\nwB . .\n. . .\n. . .\nCommands:\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(2)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". . .\n. . .\n. . wB\n")

    def test_bishop_orthogonal_ignored(self):
        fixture = (
            "Board:\nwB . .\nCommands:\n"
            "click 50 50\n"
            "click 150 50\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), "wB . .\n")

    def test_bishop_blocked_by_piece_on_diagonal(self):
        fixture = (
            "Board:\nwB . .\n. bP .\n. . bB\nCommands:\n"
            "click 50 50\n"
            "click 250 250\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), "wB . .\n. bP .\n. . bB\n")

    def test_queen_slides_orthogonally(self):
        src_x, src_y = cell_center(0, 0)
        dst_x, dst_y = cell_center(3, 0)
        fixture = (
            "Board:\nwQ . . .\nCommands:\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(3)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". . . wQ\n")

    def test_queen_slides_diagonally(self):
        src_x, src_y = cell_center(0, 0)
        dst_x, dst_y = cell_center(2, 2)
        fixture = (
            "Board:\nwQ . .\n. . .\n. . .\nCommands:\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(2)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". . .\n. . .\n. . wQ\n")

    def test_queen_cannot_leap_over_blocker(self):
        fixture = (
            "Board:\nwQ . .\n. bP .\n. . bR\nCommands:\n"
            "click 50 50\n"
            "click 250 250\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), "wQ . .\n. bP .\n. . bR\n")

    def test_queen_knight_shape_move_ignored(self):
        fixture = (
            "Board:\nwQ . .\n. . .\n. . .\nCommands:\n"
            "click 50 50\n"
            "click 150 250\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), "wQ . .\n. . .\n. . .\n")

    def test_knight_L_shape(self):
        src_x, src_y = cell_center(0, 0)
        dst_x, dst_y = cell_center(1, 2)
        fixture = (
            "Board:\nwN . .\n. . .\n. . .\nCommands:\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(2)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". . .\n. . .\n. wN .\n")

    def test_knight_straight_move_ignored(self):
        fixture = (
            "Board:\nwN . .\nCommands:\n"
            "click 50 50\n"
            "click 150 50\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), "wN . .\n")

    def test_knight_jumps_over_pieces(self):
        # wPs at (0,1), (1,0), (1,1) do not block the knight's leap to (2,1).
        src_x, src_y = cell_center(0, 0)
        dst_x, dst_y = cell_center(1, 2)
        fixture = (
            "Board:\nwN wP .\nwP wP .\n. . .\nCommands:\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(2)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". wP .\nwP wP .\n. wN .\n")

    def test_knight_captures_enemy(self):
        src_x, src_y = cell_center(0, 0)
        dst_x, dst_y = cell_center(1, 2)
        fixture = (
            "Board:\nwN . .\n. . .\n. bR .\nCommands:\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(2)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". . .\n. . .\n. wN .\n")


class TestPawnMovementRules(unittest.TestCase):
    def setUp(self):
        self.config = Config()

    def test_white_pawn_one_step_forward_legal(self):
        board = Board([[".", ".", "."], [".", "wP", "."]], self.config)
        validator = MoveValidator(board, self.config)
        self.assertTrue(validator.is_legal((1, 1), (0, 1)))

    def test_white_pawn_double_step_from_start_row_legal(self):
        # 4-row board: white start row = rows-2 = 2 (VPL: row2 -> row0).
        board = Board(
            [
                [".", ".", "."],
                [".", ".", "."],
                [".", "wP", "."],
                [".", ".", "."],
            ],
            self.config,
        )
        validator = MoveValidator(board, self.config)
        self.assertTrue(validator.is_legal((2, 1), (0, 1)))

    def test_white_pawn_double_step_not_from_start_row_illegal(self):
        # wP sits on the bottom edge (row3), NOT the start row (row2) --
        # this is the old (buggy) start row and must no longer double-step.
        board = Board(
            [
                [".", ".", "."],
                [".", ".", "."],
                [".", ".", "."],
                [".", "wP", "."],
            ],
            self.config,
        )
        validator = MoveValidator(board, self.config)
        self.assertFalse(validator.is_legal((3, 1), (1, 1)))

    def test_white_pawn_double_step_blocked_path_illegal(self):
        board = Board(
            [
                [".", ".", "."],
                [".", "bR", "."],
                [".", "wP", "."],
                [".", ".", "."],
            ],
            self.config,
        )
        validator = MoveValidator(board, self.config)
        self.assertFalse(validator.is_legal((2, 1), (0, 1)))

    def test_white_pawn_capture_forward_illegal(self):
        board = Board([[".", "bR", "."], [".", "wP", "."]], self.config)
        validator = MoveValidator(board, self.config)
        self.assertFalse(validator.is_legal((1, 1), (0, 1)))

    def test_white_pawn_diagonal_capture_legal(self):
        board = Board([["bR", ".", "."], [".", "wP", "."]], self.config)
        validator = MoveValidator(board, self.config)
        self.assertTrue(validator.is_legal((1, 1), (0, 0)))

    def test_black_pawn_one_step_down_legal(self):
        board = Board([[".", "bP", "."], [".", ".", "."]], self.config)
        validator = MoveValidator(board, self.config)
        self.assertTrue(validator.is_legal((0, 1), (1, 1)))

    def test_black_pawn_double_step_from_start_row_legal(self):
        # 4-row board: black start row = 1 (VPL: row1 -> row3).
        board = Board(
            [
                [".", ".", "."],
                [".", "bP", "."],
                [".", ".", "."],
                [".", ".", "."],
            ],
            self.config,
        )
        validator = MoveValidator(board, self.config)
        self.assertTrue(validator.is_legal((1, 1), (3, 1)))


class TestPieceRulesReturnsDestinations(unittest.TestCase):
    """Guide S7: legal_destinations(board, piece) -> set of cells. It may include
    enemy-occupied cells, and it never mutates anything."""

    def test_rook_destinations_stop_at_blockers_and_include_the_enemy(self):
        config = Config()
        board = Board([["wR", ".", "bR", "wN"]], config)
        before = render(board)
        dests = PieceRules(board, config).legal_destinations(board, "wR", (0, 0))
        self.assertEqual(dests, {(0, 1), (0, 2)})   # (0,2) is the enemy; (0,3) is behind it
        self.assertEqual(render(board), before)    # read-only


if __name__ == "__main__":
    unittest.main()
