import unittest

from engine.game import GameEngine
from model.board import Board
from model.config import Config
from tests.helpers import CFG, cell_center, make_game, render, run_fixture, wait_for
from model.game_state import GameState



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
        game, ctrl = make_game(board, config)
        ctrl.click(50, 50)    # select wR at (0,0)
        ctrl.click(250, 50)   # request move to (0,2): 2 cells -> 2000ms, starts a motion
        self.assertEqual(render(board), "wR . bR")  # not arrived yet

        reason = game.request_move((0, 0), (0, 1))
        self.assertEqual(reason.reason, GameEngine.REASON_MOTION_IN_PROGRESS)
        self.assertEqual(render(board), "wR . bR")  # still untouched

    def test_piece_moves_again_after_arrival_and_rest(self):
        # A piece that just arrived is in long_rest and refuses to move until it
        # has elapsed. This is the mentor's rule: a piece recovers after a move.
        p0_x, p0_y = cell_center(0, 0)
        p1_x, p1_y = cell_center(1, 0)
        p2_x, p2_y = cell_center(2, 0)
        fixture = (
            "Board:\nwR . .\nCommands:\n"
            f"click {p0_x} {p0_y}\n"
            f"click {p1_x} {p1_y}\n"
            f"wait {wait_for(1)}\n"
            f"wait {CFG.long_rest_ms}\n"   # let the rest elapse
            f"click {p1_x} {p1_y}\n"
            f"click {p2_x} {p2_y}\n"
            f"wait {wait_for(1)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". . wR\n")

    def test_a_piece_cannot_move_again_while_still_resting(self):
        # The same script without waiting out the rest: the second move is
        # refused, so the piece stays on cell (1,0).
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
        self.assertEqual(run_fixture(fixture), ". wR .\n")

    def test_capturing_king_ends_the_game(self):
        config = Config()
        board = Board([["wR", "bK"]], config)
        game, ctrl = make_game(board, config)
        ctrl.click(50, 50)                      # select wR at (0,0)
        ctrl.click(*cell_center(1, 0))           # request move onto bK at (0,1)
        game.wait(wait_for(1))
        self.assertEqual(render(board), ". wR")

    def test_request_move_rejected_after_game_over(self):
        config = Config()
        board = Board([["wR", "bK", "."]], config)
        game, ctrl = make_game(board, config)
        ctrl.click(50, 50)                      # select wR at (0,0)
        ctrl.click(*cell_center(1, 0))           # capture the king
        game.wait(wait_for(1))
        self.assertEqual(render(board), ". wR .")

        reason = game.request_move((0, 1), (0, 2))  # wR now at (0,1), legal-looking move
        self.assertEqual(reason.reason, GameEngine.REASON_GAME_OVER)
        self.assertEqual(render(board), ". wR .")  # untouched

    def test_non_king_capture_does_not_end_the_game(self):
        config = Config()
        board = Board([["wR", "bR"]], config)
        game, ctrl = make_game(board, config)
        ctrl.click(50, 50)
        ctrl.click(*cell_center(1, 0))
        game.wait(wait_for(1))
        self.assertEqual(render(board), ". wR")

        game.wait(config.long_rest_ms)                 # let it recover
        reason = game.request_move((0, 1), (0, 0))     # now on (0,1); move back
        self.assertTrue(reason.is_accepted)            # legal, no game_over gate


class TestGameJump(unittest.TestCase):
    def test_jump_starts_airborne_state(self):
        config = Config()
        board = Board([["wK", ".", "."]], config)
        game, ctrl = make_game(board, config)
        ctrl.jump(50, 50)  # (0,0)
        self.assertTrue(game._rta.is_airborne((0, 0)))
        self.assertEqual(render(board), "wK . .")

    def test_moving_piece_cannot_jump(self):
        config = Config()
        board = Board([["wR", ".", "."]], config)
        game, ctrl = make_game(board, config)
        ctrl.click(50, 50)   # select wR at (0,0)
        ctrl.click(150, 50)  # request move to (0,1): starts a motion
        ctrl.jump(50, 50)    # attempt to jump the now-moving wR
        self.assertFalse(game._rta.has_airborne_piece())

    def test_jump_on_empty_cell_does_nothing(self):
        config = Config()
        board = Board([["wK", ".", "."]], config)
        game, ctrl = make_game(board, config)
        ctrl.jump(150, 50)  # (0,1) is empty
        self.assertFalse(game._rta.has_airborne_piece())

    def test_second_jump_rejected_while_one_active(self):
        config = Config()
        board = Board([["wK", "wR", "."]], config)
        game, ctrl = make_game(board, config)
        ctrl.jump(50, 50)    # wK at (0,0) jumps
        ctrl.jump(150, 50)   # attempt to also jump wR at (0,1)
        self.assertTrue(game._rta.is_airborne((0, 0)))
        self.assertFalse(game._rta.is_airborne((0, 1)))

    def test_airborne_piece_cannot_be_moved(self):
        config = Config()
        board = Board([["wR", ".", "."]], config)
        game, ctrl = make_game(board, config)
        ctrl.jump(50, 50)  # wR at (0,0) is airborne
        reason = game.request_move((0, 0), (0, 1))
        self.assertEqual(reason.reason, GameEngine.REASON_AIRBORNE)
        self.assertEqual(render(board), "wR . .")

    def test_jump_rejected_after_game_over(self):
        config = Config()
        board = Board([["wR", "bK", "."]], config)
        game, ctrl = make_game(board, config)
        ctrl.click(50, 50)
        ctrl.click(150, 50)  # captures bK
        game.wait(wait_for(1))
        self.assertEqual(render(board), ". wR .")  # game over now

        ctrl.jump(150, 50)  # attempt to jump the winning wR
        self.assertFalse(game._rta.has_airborne_piece())

    def test_jump_outside_board_ignored(self):
        config = Config()
        board = Board([["wK", "."]], config)
        game, ctrl = make_game(board, config)
        ctrl.jump(999, 999)
        self.assertFalse(game._rta.has_airborne_piece())
        self.assertEqual(render(board), "wK .")

    def test_jump_command_dispatches_through_main_run(self):
        fixture = (
            "Board:\nwK . .\nCommands:\n"
            "jump 50 50\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), "wK . .\n")


class TestGameSnapshot(unittest.TestCase):
    """Guide S12/S17-Iteration-9: the snapshot must carry enough to draw with,
    without exposing mutable Board or Piece objects."""

    def setUp(self):
        self.config = Config()
        self.board = Board([["wR", ".", "."],
                            [".", ".", "bK"]], self.config)
        self.engine, self.ctrl = make_game(self.board, self.config)

    def test_snapshot_describes_the_board(self):
        s = self.engine.snapshot()
        self.assertEqual((s.board_width, s.board_height), (3, 2))
        self.assertEqual(s.cell_size, 100)
        self.assertFalse(s.game_over)

    def test_an_idle_piece_sits_on_its_cell(self):
        s = self.engine.snapshot()
        king = next(p for p in s.pieces if p.kind == "K")
        self.assertEqual((king.row, king.col), (1, 2))
        self.assertEqual((king.x, king.y), (200, 100))
        self.assertEqual(king.state, "idle")

    def test_a_moving_piece_reports_its_logical_cell_but_an_interpolated_pixel(self):
        self.engine.request_move((0, 0), (0, 2))    # 2 cells -> 2000ms
        self.engine.wait(1000)                      # exactly halfway
        rook = next(p for p in self.engine.snapshot().pieces if p.kind == "R")
        self.assertEqual((rook.row, rook.col), (0, 0))   # logically still home
        self.assertEqual((rook.x, rook.y), (100.0, 0.0)) # drawn between cells
        self.assertEqual(rook.state, "moving")

    def test_the_snapshot_carries_no_live_board_or_piece(self):
        # Guide S19: "Mistake: Passing live Board or Piece objects into Renderer."
        s = self.engine.snapshot()
        for piece in s.pieces:
            self.assertIsInstance(piece.kind, str)
            self.assertIsInstance(piece.color, str)
        self.assertNotIn("board", s._fields)
        with self.assertRaises(AttributeError):   # a namedtuple is frozen
            s.pieces[0].row = 99

    def test_the_snapshot_reports_the_selection(self):
        self.assertIsNone(self.engine.snapshot().selected_cell)
        self.assertEqual(self.engine.snapshot(selected_cell=(1, 2)).selected_cell, (1, 2))

    def test_the_snapshot_reports_game_over(self):
        self.engine.request_move((0, 0), (0, 2))
        self.engine.wait(2000)
        self.engine._game_over = True
        self.assertTrue(self.engine.snapshot().game_over)


class TestGameState(unittest.TestCase):
    def test_game_state_holds_the_board_and_the_over_flag(self):
        config = Config()
        board = Board([["wK"]], config)
        state = GameState(board)
        self.assertIs(state.board, board)
        self.assertFalse(state.game_over)


if __name__ == "__main__":
    unittest.main()
