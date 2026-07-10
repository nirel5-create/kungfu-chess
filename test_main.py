import io
import unittest

import main
from arbiter import RealTimeArbiter
from board import Board
from config import Config
from game import Game
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

    def test_config_movement_override(self):
        custom = Config(movement={"X": [(0, 1, 1, False)]})
        self.assertEqual(custom.movement, {"X": [(0, 1, 1, False)]})

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

    def test_is_legal_unrestricted_when_no_movement_rule_defined(self):
        # Extensibility (ctd_rules.md §5): a custom piece type with no rule
        # entry is unrestricted, same as pre-pawn-rules iteration-3 behavior.
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

    def test_white_pawn_double_step_illegal(self):
        board = Board(
            [[".", ".", "."], [".", ".", "."], [".", "wP", "."]], self.config
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

    def test_black_pawn_double_step_illegal(self):
        board = Board(
            [[".", "bP", "."], [".", ".", "."], [".", ".", "."]], self.config
        )
        validator = MoveValidator(board, self.config)
        self.assertFalse(validator.is_legal((0, 1), (2, 1)))


class TestPawnMotionIntegration(unittest.TestCase):
    def test_white_pawn_double_step_from_start_stays_put(self):
        src_x, src_y = cell_center(1, 2)
        dst_x, dst_y = cell_center(1, 0)
        fixture = (
            "Board:\n. . .\n. . .\n. wP .\nCommands:\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(2)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". . .\n. . .\n. wP .\n")

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
        src_x, src_y = cell_center(1, 1)
        dst_x, dst_y = cell_center(1, 0)
        fixture = (
            "Board:\n. . .\n. wP .\nCommands:\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(1)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". wP .\n. . .\n")

    def test_white_pawn_diagonal_capture_arrives(self):
        src_x, src_y = cell_center(1, 1)
        dst_x, dst_y = cell_center(0, 0)
        fixture = (
            "Board:\nbR . .\n. wP .\nCommands:\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(1)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), "wP . .\n. . .\n")


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


class TestRealTimeArbiter(unittest.TestCase):
    def setUp(self):
        self.config = Config()
        self.board = Board([["wR", ".", "."]], self.config)
        self.rta = RealTimeArbiter(self.board, self.config)

    def test_no_active_motion_initially(self):
        self.assertFalse(self.rta.has_active_motion())

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
        self.assertEqual(reason, "motion_in_progress")
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


if __name__ == "__main__":
    unittest.main()