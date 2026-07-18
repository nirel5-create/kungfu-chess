import unittest

from input.board_mapper import BoardMapper
from input.controller import Controller
from model.board import Board
from model.config import Config
from tests.helpers import FakeEngine, cell_center, run_fixture, wait_for



class TestController(unittest.TestCase):
    """The controller translates clicks into commands. It decides nothing about
    chess, never touches the board, and never advances time."""

    def setUp(self):
        self.config = Config()
        self.board = Board([["wR", ".", "wN"],
                            [".", "bR", "."]], self.config)
        self.engine = FakeEngine()
        self.ctrl = Controller(self.engine,
                               BoardMapper(self.board, self.config),
                               self.board, self.config)

    def test_first_click_on_a_piece_sets_the_selection(self):
        self.ctrl.click(50, 50)                       # (0,0) holds wR
        self.assertEqual(self.ctrl.selection, (0, 0))
        self.assertEqual(self.engine.moves, [])       # nothing commanded yet

    def test_first_click_on_an_empty_cell_leaves_the_selection_empty(self):
        self.ctrl.click(150, 50)                      # (0,1) is empty
        self.assertIsNone(self.ctrl.selection)
        self.assertEqual(self.engine.moves, [])

    def test_second_click_commands_the_move_and_clears_the_selection(self):
        self.ctrl.click(50, 50)                       # select wR at (0,0)
        self.ctrl.click(150, 150)                     # (1,1) holds bR
        self.assertEqual(self.engine.moves, [((0, 0), (1, 1))])
        self.assertIsNone(self.ctrl.selection)

    def test_clicking_another_friendly_piece_re_selects_and_commands_nothing(self):
        self.ctrl.click(50, 50)                       # select wR
        self.ctrl.click(250, 50)                      # (0,2) holds wN, also white
        self.assertEqual(self.ctrl.selection, (0, 2))
        self.assertEqual(self.engine.moves, [])

    def test_an_outside_click_cancels_the_selection_and_commands_nothing(self):
        # Guide S11. Adopted deliberately: without it there is no way at all to
        # change your mind about a selected piece.
        self.ctrl.click(50, 50)
        self.assertEqual(self.ctrl.selection, (0, 0))
        self.ctrl.click(9999, 9999)
        self.assertIsNone(self.ctrl.selection)
        self.assertEqual(self.engine.moves, [])

    def test_an_outside_click_with_nothing_selected_is_harmless(self):
        self.ctrl.click(9999, 9999)
        self.assertIsNone(self.ctrl.selection)
        self.assertEqual(self.engine.moves, [])

    def test_a_cancelled_selection_does_not_move_on_the_next_click(self):
        self.ctrl.click(50, 50)      # select wR
        self.ctrl.click(9999, 9999)  # cancel
        self.ctrl.click(150, 150)    # (1,1) is empty -> a fresh first click
        self.assertEqual(self.engine.moves, [])

    def test_jump_maps_the_pixel_to_a_cell_before_delegating(self):
        self.ctrl.jump(250, 50)                       # (0,2)
        self.assertEqual(self.engine.jumps, [(0, 2)])

    def test_jump_outside_the_board_delegates_nothing(self):
        self.ctrl.jump(9999, 9999)
        self.assertEqual(self.engine.jumps, [])


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


if __name__ == "__main__":
    unittest.main()
