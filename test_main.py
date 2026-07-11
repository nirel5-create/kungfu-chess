import io
import unittest

import main
from arbiter import RealTimeArbiter
from board import Board
from config import Config
from game import Game
from jump import Jump
from motion import Motion
from rules import MoveValidator


def run_fixture(fixture):
    out = io.StringIO()
    main.run(io.StringIO(fixture), out)
    return out.getvalue()


_CFG = Config()


def cell_center(col, row):
    c = _CFG.cell_size
    return c * col + c // 2, c * row + c // 2


def wait_for(cells):
    return cells * _CFG.piece_speed_ms


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
        src_x, src_y = cell_center(0, 0)
        dst_x, dst_y = cell_center(1, 0)
        fixture = (
            "Board:\nwR .\nCommands:\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(1)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". wR\n")

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
        p1_x, p1_y = cell_center(0, 0)
        p2_x, p2_y = cell_center(1, 0)
        p3_x, p3_y = cell_center(2, 0)
        fixture = (
            "Board:\nwP wK .\nCommands:\n"
            f"click {p1_x} {p1_y}\n"
            f"click {p2_x} {p2_y}\n"
            f"click {p3_x} {p3_y}\n"
            f"wait {wait_for(1)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), "wP . wK\n")

    def test_capture_enemy_piece(self):
        src_x, src_y = cell_center(0, 0)
        dst_x, dst_y = cell_center(1, 0)
        fixture = (
            "Board:\nwR bR\nCommands:\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(1)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". wR\n")

    def test_selection_cleared_after_move(self):
        p1_x, p1_y = cell_center(0, 0)
        p2_x, p2_y = cell_center(1, 0)
        p3_x, p3_y = cell_center(2, 0)
        fixture = (
            "Board:\nwR . .\nCommands:\n"
            f"click {p1_x} {p1_y}\n"
            f"click {p2_x} {p2_y}\n"
            f"click {p3_x} {p3_y}\n"
            f"wait {wait_for(1)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". wR .\n")

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

        board = Board([["wR", "."]], self.config)
        game = Game(board, Delayed())
        game.click(50, 50)
        game.click(150, 50)
        self.assertEqual(board.render(), "wR .")

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

    def test_promotion_target_white_pawn_on_black_start_row(self):
        board = Board([[".", "."], [".", "."], [".", "."]], self.config)  # 3 rows
        self.assertEqual(self.config.promotion_target("wP", 0, board), "wQ")

    def test_promotion_target_black_pawn_on_white_start_row(self):
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
        self.assertEqual(board.render(), "wQ .")

    def test_is_legal_unrestricted_when_no_movement_rule_defined(self):
        # Extensibility (ctd_rules.md §5): a custom piece type with no rule
        # entry is unrestricted.
        custom = Config(piece_types=("K", "X"), movement={"K": self.config.movement["K"]})
        board = Board([["wX", "."]], custom)
        validator = MoveValidator(board, custom)
        self.assertTrue(validator.is_legal((0, 0), (0, 1)))


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
        board = Board(
            [[".", ".", "."], [".", ".", "."], [".", "wP", "."]], self.config
        )
        validator = MoveValidator(board, self.config)
        self.assertTrue(validator.is_legal((2, 1), (0, 1)))

    def test_white_pawn_double_step_not_from_start_row_illegal(self):
        board = Board(
            [[".", ".", "."], [".", ".", "."], [".", "wP", "."], [".", ".", "."]],
            self.config,
        )
        validator = MoveValidator(board, self.config)
        self.assertFalse(validator.is_legal((2, 1), (0, 1)))

    def test_white_pawn_double_step_blocked_path_illegal(self):
        board = Board(
            [[".", ".", "."], [".", "bR", "."], [".", "wP", "."]], self.config
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
        board = Board(
            [[".", "bP", "."], [".", ".", "."], [".", ".", "."]], self.config
        )
        validator = MoveValidator(board, self.config)
        self.assertTrue(validator.is_legal((0, 1), (2, 1)))


class TestPawnMotionIntegration(unittest.TestCase):
    def test_white_pawn_double_step_from_start_arrives(self):
        src_x, src_y = cell_center(1, 3)
        dst_x, dst_y = cell_center(1, 1)
        fixture = (
            "Board:\n. . .\n. . .\n. . .\n. wP .\nCommands:\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(2)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". . .\n. wP .\n. . .\n. . .\n")

    def test_white_pawn_cannot_capture_forward(self):
        src_x, src_y = cell_center(1, 1)
        dst_x, dst_y = cell_center(1, 0)
        fixture = (
            "Board:\n. bR .\n. wP .\nCommands:\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(1)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". bR .\n. wP .\n")

    def test_white_pawn_one_step_forward_arrives(self):
        src_x, src_y = cell_center(1, 2)
        dst_x, dst_y = cell_center(1, 1)
        fixture = (
            "Board:\n. . .\n. . .\n. wP .\nCommands:\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(1)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". . .\n. wP .\n. . .\n")

    def test_white_pawn_diagonal_capture_arrives(self):
        src_x, src_y = cell_center(1, 2)
        dst_x, dst_y = cell_center(0, 1)
        fixture = (
            "Board:\n. . .\nbR . .\n. wP .\nCommands:\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(1)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". . .\nwP . .\n. . .\n")


class TestPawnPromotionIntegration(unittest.TestCase):
    def test_white_pawn_promotes_to_queen_on_arrival(self):
        src_x, src_y = cell_center(1, 1)
        dst_x, dst_y = cell_center(1, 0)
        fixture = (
            "Board:\n. . .\n. wP .\nCommands:\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(1)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". wQ .\n. . .\n")

    def test_black_pawn_promotes_to_queen_on_arrival(self):
        src_x, src_y = cell_center(1, 0)
        dst_x, dst_y = cell_center(1, 1)
        fixture = (
            "Board:\n. bP .\n. . .\nCommands:\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(1)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". . .\n. bQ .\n")


class TestMotion(unittest.TestCase):
    def test_motion_stores_piece_source_destination_and_arrival_time(self):
        motion = Motion("wR", (0, 1), (2, 1), 2000)
        self.assertEqual(motion.piece, "wR")
        self.assertEqual(motion.source, (0, 1))
        self.assertEqual(motion.destination, (2, 1))
        self.assertEqual(motion.arrival_time, 2000)

    def test_motion_equality_is_by_value(self):
        self.assertEqual(
            Motion("wR", (0, 1), (2, 1), 2000),
            Motion("wR", (0, 1), (2, 1), 2000),
        )


class TestJump(unittest.TestCase):
    def test_jump_stores_piece_cell_and_end_time(self):
        jump = Jump("wR", (0, 1), 1000)
        self.assertEqual(jump.piece, "wR")
        self.assertEqual(jump.cell, (0, 1))
        self.assertEqual(jump.end_time, 1000)

    def test_jump_equality_is_by_value(self):
        self.assertEqual(Jump("wR", (0, 1), 1000), Jump("wR", (0, 1), 1000))


class TestRealTimeArbiter(unittest.TestCase):
    def setUp(self):
        self.config = Config()
        self.board = Board([["wR", ".", "."]], self.config)
        self.rta = RealTimeArbiter(self.board, self.config)

    def test_no_active_motion_initially(self):
        self.assertFalse(self.rta.has_active_motion())

    def test_no_airborne_piece_initially(self):
        self.assertFalse(self.rta.has_airborne_piece())
        self.assertFalse(self.rta.is_airborne((0, 0)))

    def test_start_jump_marks_airborne_and_leaves_board_unchanged(self):
        self.rta.start_jump("wR", (0, 0))
        self.assertTrue(self.rta.has_airborne_piece())
        self.assertTrue(self.rta.is_airborne((0, 0)))
        self.assertFalse(self.rta.is_airborne((0, 1)))
        self.assertEqual(self.board.render(), "wR . .")

    def test_is_moving_true_for_active_motion_source_only(self):
        self.rta.start_motion("wR", (0, 0), (0, 1))
        self.assertTrue(self.rta.is_moving((0, 0)))
        self.assertFalse(self.rta.is_moving((0, 1)))

    def test_is_moving_false_with_no_active_motion(self):
        self.assertFalse(self.rta.is_moving((0, 0)))

    def test_reversal_captures_enemy_arriving_exactly_at_end_time(self):
        board = Board([["wK", "bR", "."]], self.config)
        rta = RealTimeArbiter(board, self.config)
        rta.start_jump("wK", (0, 0))  # end_time = 1000
        rta.start_motion("bR", (0, 1), (0, 0))  # 1 cell -> 1000ms, arrival_time = 1000
        events = rta.advance_time(1000)
        self.assertEqual(events, [Motion("bR", (0, 1), (0, 0), 1000)])
        self.assertEqual(board.render(), "wK . .")  # jumper stays, arriver removed
        self.assertFalse(rta.has_active_motion())
        self.assertFalse(rta.has_airborne_piece())  # jump resolved via capture

    def test_arrival_after_jump_window_lands_normally(self):
        board = Board([["wK", ".", "bR"]], self.config)
        rta = RealTimeArbiter(board, self.config)
        rta.start_jump("wK", (0, 0))  # end_time = 1000
        rta.start_motion("bR", (0, 2), (0, 0))  # 2 cells -> 2000ms, arrival_time = 2000
        events = rta.advance_time(2000)
        self.assertEqual(events, [Motion("bR", (0, 2), (0, 0), 2000)])
        self.assertEqual(board.render(), "bR . .")  # enemy lands normally, capturing wK
        self.assertTrue(rta.king_was_captured())

    def test_friendly_arrival_at_airborne_cell_not_reversed(self):
        board = Board([["wK", "wR", "."]], self.config)
        rta = RealTimeArbiter(board, self.config)
        rta.start_jump("wK", (0, 0))  # end_time = 1000
        rta.start_motion("wR", (0, 1), (0, 0))  # friendly, 1 cell -> 1000ms
        events = rta.advance_time(1000)
        self.assertEqual(events, [Motion("wR", (0, 1), (0, 0), 1000)])
        self.assertEqual(board.render(), "wR . .")  # friendly lands normally, not reversed

    def test_jump_times_out_with_no_arrival(self):
        board = Board([["wK", ".", "."]], self.config)
        rta = RealTimeArbiter(board, self.config)
        rta.start_jump("wK", (0, 0))
        rta.advance_time(1000)
        self.assertFalse(rta.has_airborne_piece())
        self.assertEqual(board.render(), "wK . .")

    def test_reversal_capturing_enemy_king_sets_king_was_captured(self):
        board = Board([["wR", "bK", "."]], self.config)
        rta = RealTimeArbiter(board, self.config)
        rta.start_jump("wR", (0, 0))
        rta.start_motion("bK", (0, 1), (0, 0))  # enemy king arrives, gets reversed/captured
        rta.advance_time(1000)
        self.assertTrue(rta.king_was_captured())
        self.assertEqual(board.render(), "wR . .")

    def test_reversal_skips_promotion_for_arriving_pawn(self):
        board = Board([["bR", "."], ["wP", "."]], self.config)  # 2 rows
        rta = RealTimeArbiter(board, self.config)
        rta.start_jump("bR", (0, 0))  # end_time = 1000
        rta.start_motion("wP", (1, 0), (0, 0))  # 1 cell -> 1000ms, arrival_time = 1000, promotion row
        rta.advance_time(1000)
        self.assertEqual(board.render(), "bR .\n. .")  # pawn captured mid-air, no promotion

    def test_start_motion_marks_active_and_leaves_board_unchanged(self):
        self.rta.start_motion("wR", (0, 0), (0, 2))
        self.assertTrue(self.rta.has_active_motion())
        self.assertEqual(self.board.render(), "wR . .")

    def test_advance_time_before_arrival_does_not_apply_move(self):
        self.rta.start_motion("wR", (0, 0), (0, 1))  # 1 cell -> 1000ms
        self.assertEqual(self.rta.advance_time(999), [])
        self.assertEqual(self.board.render(), "wR . .")
        self.assertTrue(self.rta.has_active_motion())

    def test_advance_time_at_exact_arrival_applies_move(self):
        self.rta.start_motion("wR", (0, 0), (0, 1))
        events = self.rta.advance_time(1000)
        self.assertEqual(events, [Motion("wR", (0, 0), (0, 1), 1000)])
        self.assertEqual(self.board.render(), ". wR .")
        self.assertFalse(self.rta.has_active_motion())

    def test_partial_waits_accumulate_to_arrival(self):
        self.rta.start_motion("wR", (0, 0), (0, 2))  # 2 cells -> 2000ms
        self.assertEqual(self.rta.advance_time(400), [])
        self.assertEqual(self.rta.advance_time(600), [])  # 1000 total, not there yet
        self.assertEqual(self.board.render(), "wR . .")
        self.assertEqual(
            self.rta.advance_time(1000),  # 2000 total -> arrives
            [Motion("wR", (0, 0), (0, 2), 2000)],
        )
        self.assertEqual(self.board.render(), ". . wR")

    def test_advance_time_with_no_active_motion_is_noop(self):
        self.assertEqual(self.rta.advance_time(500), [])
        self.assertEqual(self.board.render(), "wR . .")

    def test_can_start_new_motion_immediately_after_arrival(self):
        self.rta.start_motion("wR", (0, 0), (0, 1))  # 1 cell -> 1000ms
        self.rta.advance_time(1000)  # arrives; board is now ". wR ."
        self.assertFalse(self.rta.has_active_motion())

        self.rta.start_motion("wR", (0, 1), (0, 2))  # immediately, no extra wait
        self.assertTrue(self.rta.has_active_motion())

    def test_king_was_captured_true_on_arrival_into_enemy_king(self):
        board = Board([["wR", "bK"]], self.config)
        rta = RealTimeArbiter(board, self.config)
        rta.start_motion("wR", (0, 0), (0, 1))  # 1 cell -> 1000ms
        self.assertFalse(rta.king_was_captured())  # not yet arrived
        rta.advance_time(1000)
        self.assertTrue(rta.king_was_captured())
        self.assertEqual(board.render(), ". wR")

    def test_king_was_captured_false_for_non_king_capture(self):
        board = Board([["wR", "bR"]], self.config)
        rta = RealTimeArbiter(board, self.config)
        rta.start_motion("wR", (0, 0), (0, 1))
        rta.advance_time(1000)
        self.assertFalse(rta.king_was_captured())
        self.assertEqual(board.render(), ". wR")

    def test_white_pawn_promotes_to_queen_on_arrival(self):
        board = Board([[".", "."], [".", "."], [".", "wP"]], self.config)  # 3 rows
        rta = RealTimeArbiter(board, self.config)
        rta.start_motion("wP", (2, 1), (1, 1))  # 1 cell -> 1000ms, not yet promotion row
        rta.advance_time(1000)
        self.assertEqual(board.render(), ". .\n. wP\n. .")

        rta.start_motion("wP", (1, 1), (0, 1))  # arrives on row 0 -> promotes
        rta.advance_time(1000)
        self.assertEqual(board.render(), ". wQ\n. .\n. .")

    def test_black_pawn_promotes_to_queen_on_arrival(self):
        board = Board([[".", "bP"], [".", "."], [".", "."]], self.config)  # 3 rows
        rta = RealTimeArbiter(board, self.config)
        rta.start_motion("bP", (0, 1), (2, 1))  # 2 cells -> 2000ms, arrives on row 2
        rta.advance_time(2000)
        self.assertEqual(board.render(), ". .\n. .\n. bQ")

    def test_non_promoting_arrival_stays_a_pawn(self):
        board = Board([[".", "."], [".", "."], [".", "wP"]], self.config)  # 3 rows
        rta = RealTimeArbiter(board, self.config)
        rta.start_motion("wP", (2, 1), (1, 1))  # arrives mid-board, no promotion
        rta.advance_time(1000)
        self.assertEqual(board.render(), ". .\n. wP\n. .")

    def test_promoted_queen_has_queen_movement(self):
        board = Board(
            [[".", ".", "."], [".", ".", "."], [".", "wP", "."]], self.config
        )  # 3 rows
        rta = RealTimeArbiter(board, self.config)
        rta.start_motion("wP", (2, 1), (0, 1))  # 2 cells -> 2000ms, from start row, promotes
        rta.advance_time(2000)
        self.assertEqual(board.render(), ". wQ .\n. . .\n. . .")

        validator = MoveValidator(board, self.config)
        # (0,1) -> (0,2): sideways -- no pawn ray permits dr=0, but legal for a queen.
        self.assertTrue(validator.is_legal((0, 1), (0, 2)))


class TestGameJump(unittest.TestCase):
    def test_jump_starts_airborne_state(self):
        config = Config()
        board = Board([["wK", ".", "."]], config)
        game = Game(board, config)
        game.jump(50, 50)  # (0,0)
        self.assertTrue(game._rta.is_airborne((0, 0)))
        self.assertEqual(board.render(), "wK . .")

    def test_moving_piece_cannot_jump(self):
        config = Config()
        board = Board([["wR", ".", "."]], config)
        game = Game(board, config)
        game.click(50, 50)   # select wR at (0,0)
        game.click(150, 50)  # request move to (0,1): starts a motion
        game.jump(50, 50)    # attempt to jump the now-moving wR
        self.assertFalse(game._rta.has_airborne_piece())

    def test_jump_on_empty_cell_does_nothing(self):
        config = Config()
        board = Board([["wK", ".", "."]], config)
        game = Game(board, config)
        game.jump(150, 50)  # (0,1) is empty
        self.assertFalse(game._rta.has_airborne_piece())

    def test_second_jump_rejected_while_one_active(self):
        config = Config()
        board = Board([["wK", "wR", "."]], config)
        game = Game(board, config)
        game.jump(50, 50)    # wK at (0,0) jumps
        game.jump(150, 50)   # attempt to also jump wR at (0,1)
        self.assertTrue(game._rta.is_airborne((0, 0)))
        self.assertFalse(game._rta.is_airborne((0, 1)))

    def test_airborne_piece_cannot_be_moved(self):
        config = Config()
        board = Board([["wR", ".", "."]], config)
        game = Game(board, config)
        game.jump(50, 50)  # wR at (0,0) is airborne
        reason = game._request_move((0, 0), (0, 1))
        self.assertEqual(reason, Game.REASON_AIRBORNE)
        self.assertEqual(board.render(), "wR . .")

    def test_jump_rejected_after_game_over(self):
        config = Config()
        board = Board([["wR", "bK", "."]], config)
        game = Game(board, config)
        game.click(50, 50)
        game.click(150, 50)  # captures bK
        game.wait(wait_for(1))
        self.assertEqual(board.render(), ". wR .")  # game over now

        game.jump(150, 50)  # attempt to jump the winning wR
        self.assertFalse(game._rta.has_airborne_piece())

    def test_jump_outside_board_ignored(self):
        config = Config()
        board = Board([["wK", "."]], config)
        game = Game(board, config)
        game.jump(999, 999)
        self.assertFalse(game._rta.has_airborne_piece())
        self.assertEqual(board.render(), "wK .")

    def test_jump_command_dispatches_through_main_run(self):
        fixture = (
            "Board:\nwK . .\nCommands:\n"
            "jump 50 50\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), "wK . .\n")


class TestJumpIntegration(unittest.TestCase):
    def test_jump_reversal_matches_vpl_test_2(self):
        jump_x, jump_y = cell_center(0, 0)
        src_x, src_y = cell_center(1, 0)
        dst_x, dst_y = cell_center(0, 0)
        fixture = (
            "Board:\nwK bR .\nCommands:\n"
            f"jump {jump_x} {jump_y}\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(1)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), "wK . .\n")

    def test_jump_with_no_arrival_lands_and_can_move_again(self):
        jump_x, jump_y = cell_center(0, 0)
        src_x, src_y = cell_center(0, 0)
        dst_x, dst_y = cell_center(1, 0)
        fixture = (
            "Board:\nwK . .\nCommands:\n"
            f"jump {jump_x} {jump_y}\n"
            f"wait {wait_for(1)}\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(1)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". wK .\n")


class TestGameMotionWiring(unittest.TestCase):
    def test_two_cell_move_not_arrived_after_partial_wait(self):
        # Exact spec integration fixture: 2-cell move needs 2000ms; only
        # 1000ms elapsed, so the board must still show the pre-move state.
        fixture = (
            "Board:\n. wR .\n. . .\n. . bK\nCommands:\n"
            "click 150 50\n"
            "click 150 250\n"
            "wait 1000\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". wR .\n. . .\n. . bK\n")

    def test_second_move_rejected_with_motion_in_progress(self):
        config = Config()
        board = Board([["wR", ".", "bR"]], config)
        game = Game(board, config)
        game.click(50, 50)    # select wR at (0,0)
        game.click(250, 50)   # request move to (0,2): 2 cells -> 2000ms, starts a motion
        self.assertEqual(board.render(), "wR . bR")  # not arrived yet

        reason = game._request_move((0, 0), (0, 1))
        self.assertEqual(reason, Game.REASON_MOTION_IN_PROGRESS)
        self.assertEqual(board.render(), "wR . bR")  # still untouched

    def test_piece_moves_again_immediately_after_arrival(self):
        p0_x, p0_y = cell_center(0, 0)
        p1_x, p1_y = cell_center(1, 0)
        p2_x, p2_y = cell_center(2, 0)
        fixture = (
            "Board:\nwR . .\nCommands:\n"
            f"click {p0_x} {p0_y}\n"
            f"click {p1_x} {p1_y}\n"
            f"wait {wait_for(1)}\n"
            f"click {p1_x} {p1_y}\n"
            f"click {p2_x} {p2_y}\n"
            f"wait {wait_for(1)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". . wR\n")

    def test_capturing_king_ends_the_game(self):
        config = Config()
        board = Board([["wR", "bK"]], config)
        game = Game(board, config)
        game.click(50, 50)                      # select wR at (0,0)
        game.click(*cell_center(1, 0))           # request move onto bK at (0,1)
        game.wait(wait_for(1))
        self.assertEqual(board.render(), ". wR")

    def test_request_move_rejected_after_game_over(self):
        config = Config()
        board = Board([["wR", "bK", "."]], config)
        game = Game(board, config)
        game.click(50, 50)                      # select wR at (0,0)
        game.click(*cell_center(1, 0))           # capture the king
        game.wait(wait_for(1))
        self.assertEqual(board.render(), ". wR .")

        reason = game._request_move((0, 1), (0, 2))  # wR now at (0,1), legal-looking move
        self.assertEqual(reason, Game.REASON_GAME_OVER)
        self.assertEqual(board.render(), ". wR .")  # untouched

    def test_non_king_capture_does_not_end_the_game(self):
        config = Config()
        board = Board([["wR", "bR"]], config)
        game = Game(board, config)
        game.click(50, 50)
        game.click(*cell_center(1, 0))
        game.wait(wait_for(1))
        self.assertEqual(board.render(), ". wR")

        reason = game._request_move((0, 1), (0, 0))  # move back, should still work
        self.assertIsNone(reason)  # accepted (legal, no game_over gate)


if __name__ == "__main__":
    unittest.main()