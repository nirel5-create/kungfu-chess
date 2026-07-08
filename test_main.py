import io
import unittest

import main
from main import Board, Config, Game


def run_fixture(fixture):
    out = io.StringIO()
    main.run(io.StringIO(fixture), out)
    return out.getvalue()


class TestBoardValidationAndPrint(unittest.TestCase):
    def test_print_board_renders_start_position(self):
        fixture = (
            "Board:\n"
            "wR wN wB wQ wK wB wN wR\n"
            "wP wP wP wP wP wP wP wP\n"
            ". . . . . . . .\n"
            ". . . . . . . .\n"
            ". . . . . . . .\n"
            ". . . . . . . .\n"
            "bP bP bP bP bP bP bP bP\n"
            "bR bN bB bQ bK bB bN bR\n"
            "Commands:\n"
            "print board\n"
        )
        expected = (
            "wR wN wB wQ wK wB wN wR\n"
            "wP wP wP wP wP wP wP wP\n"
            ". . . . . . . .\n"
            ". . . . . . . .\n"
            ". . . . . . . .\n"
            ". . . . . . . .\n"
            "bP bP bP bP bP bP bP bP\n"
            "bR bN bB bQ bK bB bN bR\n"
        )
        self.assertEqual(run_fixture(fixture), expected)

    def test_leading_space_before_section_marker(self):
        fixture = " Board:\nwK .\n. .\nCommands:\nprint board\n"
        self.assertEqual(run_fixture(fixture), "wK .\n. .\n")

    def test_row_width_mismatch(self):
        fixture = "Board:\nwR wN wB\nwP wP\nCommands:\nprint board\n"
        self.assertEqual(run_fixture(fixture), "ERROR ROW_WIDTH_MISMATCH\n")

    def test_unknown_token_letter(self):
        fixture = "Board:\nwR wN wZ\nCommands:\nprint board\n"
        self.assertEqual(run_fixture(fixture), "ERROR UNKNOWN_TOKEN\n")

    def test_unknown_token_case_sensitive(self):
        fixture = "Board:\nWR wN wB\nCommands:\nprint board\n"
        self.assertEqual(run_fixture(fixture), "ERROR UNKNOWN_TOKEN\n")

    def test_unknown_token_wrong_color_char(self):
        fixture = "Board:\nxK . .\nCommands:\nprint board\n"
        self.assertEqual(run_fixture(fixture), "ERROR UNKNOWN_TOKEN\n")

    def test_width_mismatch_precedes_unknown_token(self):
        fixture = "Board:\nwR wN\nwZ wP wP\nCommands:\nprint board\n"
        self.assertEqual(run_fixture(fixture), "ERROR ROW_WIDTH_MISMATCH\n")

    def test_no_commands_no_output(self):
        fixture = "Board:\nwR wN\nwP wP\nCommands:\n"
        self.assertEqual(run_fixture(fixture), "")

    def test_multiple_print_repeats(self):
        fixture = "Board:\n. .\nCommands:\nprint board\nprint board\n"
        self.assertEqual(run_fixture(fixture), ". .\n. .\n")

    def test_unknown_command_ignored(self):
        fixture = "Board:\n. .\nCommands:\ndo nothing\n"
        self.assertEqual(run_fixture(fixture), "")

    def test_empty_board_valid(self):
        fixture = "Board:\n. . .\n. . .\nCommands:\nprint board\n"
        self.assertEqual(run_fixture(fixture), ". . .\n. . .\n")


class TestClickSelectionAndMove(unittest.TestCase):
    def test_move_selected_piece_to_empty_cell(self):
        fixture = (
            "Board:\nwP .\nCommands:\n"
            "click 50 50\n"
            "click 150 50\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". wP\n")

    def test_click_empty_with_no_selection_ignored(self):
        fixture = "Board:\n. wP\nCommands:\nclick 50 50\nprint board\n"
        self.assertEqual(run_fixture(fixture), ". wP\n")

    def test_click_outside_board_ignored(self):
        fixture = (
            "Board:\nwP .\nCommands:\n"
            "click 999 999\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), "wP .\n")

    def test_click_negative_coordinate_ignored(self):
        fixture = (
            "Board:\nwP .\nCommands:\n"
            "click 50 50\n"
            "click -10 50\n"
            "print board\n"
        )
        # piece selected, negative click ignored, selection stays put
        self.assertEqual(run_fixture(fixture), "wP .\n")

    def test_friendly_click_replaces_selection(self):
        # wK is used so the follow-up move (one square right) is a legal king step.
        fixture = (
            "Board:\nwP wK .\nCommands:\n"
            "click 50 50\n"
            "click 150 50\n"
            "click 250 50\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), "wP . wK\n")

    def test_capture_enemy_piece(self):
        fixture = (
            "Board:\nwP bP\nCommands:\n"
            "click 50 50\n"
            "click 150 50\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". wP\n")

    def test_selection_cleared_after_move(self):
        fixture = (
            "Board:\nwP . .\nCommands:\n"
            "click 50 50\n"
            "click 150 50\n"
            "click 250 50\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". wP .\n")

    def test_wait_advances_clock_without_changing_board(self):
        fixture = (
            "Board:\nwP .\nCommands:\n"
            "wait 500\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), "wP .\n")


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

        board = Board([["wP", "."]], self.config)
        game = Game(board, Delayed())
        game.click(50, 50)
        game.click(150, 50)
        self.assertEqual(board.render(), "wP .")

    def test_default_movement_covers_KQRBN_but_not_pawn(self):
        # Rules-as-data (§9): the movement table is a config attribute.
        for piece in ("K", "Q", "R", "B", "N"):
            self.assertIn(piece, self.config.movement)
        self.assertNotIn("P", self.config.movement)

    def test_config_movement_override(self):
        custom = Config(movement={"X": [(0, 1, 1, False)]})
        self.assertEqual(custom.movement, {"X": [(0, 1, 1, False)]})


class TestMovementRules(unittest.TestCase):
    """One click selects, the next click attempts a move. Illegal moves are
    silently ignored (board unchanged)."""

    def test_king_one_step_diagonally(self):
        fixture = (
            "Board:\nwK . .\n. . .\n. . .\nCommands:\n"
            "click 50 50\n"
            "click 150 150\n"
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
        fixture = (
            "Board:\nwR . . .\nCommands:\n"
            "click 50 50\n"
            "click 350 50\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". . . wR\n")

    def test_rook_slides_along_file(self):
        fixture = (
            "Board:\nwR .\n. .\n. .\n. .\nCommands:\n"
            "click 50 50\n"
            "click 50 350\n"
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
        fixture = (
            "Board:\nwR . . bR\nCommands:\n"
            "click 50 50\n"
            "click 350 50\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". . . wR\n")

    def test_bishop_slides_diagonally(self):
        fixture = (
            "Board:\nwB . .\n. . .\n. . .\nCommands:\n"
            "click 50 50\n"
            "click 250 250\n"
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
        fixture = (
            "Board:\nwQ . . .\nCommands:\n"
            "click 50 50\n"
            "click 350 50\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". . . wQ\n")

    def test_queen_slides_diagonally(self):
        fixture = (
            "Board:\nwQ . .\n. . .\n. . .\nCommands:\n"
            "click 50 50\n"
            "click 250 250\n"
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
        fixture = (
            "Board:\nwN . .\n. . .\n. . .\nCommands:\n"
            "click 50 50\n"
            "click 150 250\n"
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
        fixture = (
            "Board:\nwN wP .\nwP wP .\n. . .\nCommands:\n"
            "click 50 50\n"
            "click 150 250\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". wP .\nwP wP .\n. wN .\n")

    def test_knight_captures_enemy(self):
        fixture = (
            "Board:\nwN . .\n. . .\n. bR .\nCommands:\n"
            "click 50 50\n"
            "click 150 250\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". . .\n. . .\n. wN .\n")


if __name__ == "__main__":
    unittest.main()