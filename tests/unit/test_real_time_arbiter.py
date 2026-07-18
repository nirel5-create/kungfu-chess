import unittest

from model.board import Board
from model.config import Config
from realtime.arbiter import RealTimeArbiter
from realtime.motion import Motion
from tests.helpers import MoveValidator, render



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
        self.assertEqual(render(self.board), "wR . .")

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
        self.assertEqual(render(board), "wK . .")  # jumper stays, arriver removed
        self.assertFalse(rta.has_active_motion())
        self.assertFalse(rta.has_airborne_piece())  # jump resolved via capture

    def test_arrival_after_jump_window_lands_normally(self):
        board = Board([["wK", ".", "bR"]], self.config)
        rta = RealTimeArbiter(board, self.config)
        rta.start_jump("wK", (0, 0))  # end_time = 1000
        rta.start_motion("bR", (0, 2), (0, 0))  # 2 cells -> 2000ms, arrival_time = 2000
        events = rta.advance_time(2000)
        self.assertEqual(events, [Motion("bR", (0, 2), (0, 0), 2000)])
        self.assertEqual(render(board), "bR . .")  # enemy lands normally, capturing wK
        self.assertTrue(rta.king_was_captured())

    def test_friendly_arrival_at_airborne_cell_not_reversed(self):
        board = Board([["wK", "wR", "."]], self.config)
        rta = RealTimeArbiter(board, self.config)
        rta.start_jump("wK", (0, 0))  # end_time = 1000
        rta.start_motion("wR", (0, 1), (0, 0))  # friendly, 1 cell -> 1000ms
        events = rta.advance_time(1000)
        self.assertEqual(events, [Motion("wR", (0, 1), (0, 0), 1000)])
        # No reversal: a reversal would delete the arriver ("wK . ."). Instead
        # the arrival is cancelled -- the destination holds a friendly piece.
        self.assertEqual(render(board), "wK wR .")

    def test_jump_times_out_with_no_arrival(self):
        board = Board([["wK", ".", "."]], self.config)
        rta = RealTimeArbiter(board, self.config)
        rta.start_jump("wK", (0, 0))
        rta.advance_time(1000)
        self.assertFalse(rta.has_airborne_piece())
        self.assertEqual(render(board), "wK . .")

    def test_reversal_capturing_enemy_king_sets_king_was_captured(self):
        board = Board([["wR", "bK", "."]], self.config)
        rta = RealTimeArbiter(board, self.config)
        rta.start_jump("wR", (0, 0))
        rta.start_motion("bK", (0, 1), (0, 0))  # enemy king arrives, gets reversed/captured
        rta.advance_time(1000)
        self.assertTrue(rta.king_was_captured())
        self.assertEqual(render(board), "wR . .")

    def test_reversal_skips_promotion_for_arriving_pawn(self):
        board = Board([["bR", "."], ["wP", "."]], self.config)  # 2 rows
        rta = RealTimeArbiter(board, self.config)
        rta.start_jump("bR", (0, 0))  # end_time = 1000
        rta.start_motion("wP", (1, 0), (0, 0))  # 1 cell -> 1000ms, arrival_time = 1000, promotion row
        rta.advance_time(1000)
        self.assertEqual(render(board), "bR .\n. .")  # pawn captured mid-air, no promotion

    def test_start_motion_marks_active_and_leaves_board_unchanged(self):
        self.rta.start_motion("wR", (0, 0), (0, 2))
        self.assertTrue(self.rta.has_active_motion())
        self.assertEqual(render(self.board), "wR . .")

    def test_advance_time_before_arrival_does_not_apply_move(self):
        self.rta.start_motion("wR", (0, 0), (0, 1))  # 1 cell -> 1000ms
        self.assertEqual(self.rta.advance_time(999), [])
        self.assertEqual(render(self.board), "wR . .")
        self.assertTrue(self.rta.has_active_motion())

    def test_advance_time_at_exact_arrival_applies_move(self):
        self.rta.start_motion("wR", (0, 0), (0, 1))
        events = self.rta.advance_time(1000)
        self.assertEqual(events, [Motion("wR", (0, 0), (0, 1), 1000)])
        self.assertEqual(render(self.board), ". wR .")
        self.assertFalse(self.rta.has_active_motion())

    def test_partial_waits_accumulate_to_arrival(self):
        self.rta.start_motion("wR", (0, 0), (0, 2))  # 2 cells -> 2000ms
        self.assertEqual(self.rta.advance_time(400), [])
        self.assertEqual(self.rta.advance_time(600), [])  # 1000 total, not there yet
        self.assertEqual(render(self.board), "wR . .")
        self.assertEqual(
            self.rta.advance_time(1000),  # 2000 total -> arrives
            [Motion("wR", (0, 0), (0, 2), 2000)],
        )
        self.assertEqual(render(self.board), ". . wR")

    def test_advance_time_with_no_active_motion_is_noop(self):
        self.assertEqual(self.rta.advance_time(500), [])
        self.assertEqual(render(self.board), "wR . .")

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
        self.assertEqual(render(board), ". wR")

    def test_king_was_captured_false_for_non_king_capture(self):
        board = Board([["wR", "bR"]], self.config)
        rta = RealTimeArbiter(board, self.config)
        rta.start_motion("wR", (0, 0), (0, 1))
        rta.advance_time(1000)
        self.assertFalse(rta.king_was_captured())
        self.assertEqual(render(board), ". wR")

    def test_white_pawn_promotes_to_queen_on_arrival(self):
        board = Board([[".", "."], [".", "."], [".", "wP"]], self.config)  # 3 rows
        rta = RealTimeArbiter(board, self.config)
        rta.start_motion("wP", (2, 1), (1, 1))  # 1 cell -> 1000ms, not yet promotion row
        rta.advance_time(1000)
        self.assertEqual(render(board), ". .\n. wP\n. .")

        rta.start_motion("wP", (1, 1), (0, 1))  # arrives on row 0 -> promotes
        rta.advance_time(1000)
        self.assertEqual(render(board), ". wQ\n. .\n. .")

    def test_black_pawn_promotes_to_queen_on_arrival(self):
        board = Board([[".", "bP"], [".", "."], [".", "."]], self.config)  # 3 rows
        rta = RealTimeArbiter(board, self.config)
        rta.start_motion("bP", (0, 1), (2, 1))  # 2 cells -> 2000ms, arrives on row 2
        rta.advance_time(2000)
        self.assertEqual(render(board), ". .\n. .\n. bQ")

    def test_non_promoting_arrival_stays_a_pawn(self):
        board = Board([[".", "."], [".", "."], [".", "wP"]], self.config)  # 3 rows
        rta = RealTimeArbiter(board, self.config)
        rta.start_motion("wP", (2, 1), (1, 1))  # arrives mid-board, no promotion
        rta.advance_time(1000)
        self.assertEqual(render(board), ". .\n. wP\n. .")

    def test_promoted_queen_has_queen_movement(self):
        board = Board(
            [[".", ".", "."], [".", ".", "."], [".", "wP", "."]], self.config
        )  # 3 rows
        rta = RealTimeArbiter(board, self.config)
        rta.start_motion("wP", (2, 1), (0, 1))  # 2 cells -> 2000ms, arrives on the promotion edge
        rta.advance_time(2000)
        self.assertEqual(render(board), ". wQ .\n. . .\n. . .")

        validator = MoveValidator(board, self.config)
        # (0,1) -> (0,2): sideways -- no pawn ray permits dr=0, but legal for a queen.
        self.assertTrue(validator.is_legal((0, 1), (0, 2)))


if __name__ == "__main__":
    unittest.main()
