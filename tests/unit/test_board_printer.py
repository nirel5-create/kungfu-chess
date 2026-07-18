import unittest

from boardio.board_parser import BoardParser
from boardio.board_printer import BoardPrinter
from model.board import Board
from model.config import Config
from tests.helpers import make_game



class TestBoardPrinter(unittest.TestCase):
    def test_round_trips_a_simple_board(self):
        text = "wR . bK\n. wN ."
        board = BoardParser(Config()).parse(text)
        self.assertEqual(BoardPrinter().print(board), text)

    def test_prints_logical_occupancy_not_animation_position(self):
        # Guide S13: a piece in flight is still printed on its source cell.
        config = Config()
        board = Board([["wR", ".", "."]], config)
        engine, _ = make_game(board, config)
        engine.request_move((0, 0), (0, 2))
        engine.wait(1000)                       # halfway: not arrived
        self.assertEqual(BoardPrinter().print(board), "wR . .")


if __name__ == "__main__":
    unittest.main()
