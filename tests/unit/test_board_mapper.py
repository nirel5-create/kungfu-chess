import unittest

from input.board_mapper import BoardMapper
from model.board import Board
from model.config import Config



class TestBoardMapper(unittest.TestCase):
    """The only class that knows a cell is Config.cell_size pixels wide."""

    def setUp(self):
        self.config = Config()
        self.board = Board([[".", "."], [".", "."]], self.config)
        self.mapper = BoardMapper(self.board, self.config)

    def test_pixels_map_to_the_containing_cell(self):
        self.assertEqual(self.mapper.pixel_to_cell(0, 0), (0, 0))
        self.assertEqual(self.mapper.pixel_to_cell(99, 99), (0, 0))
        self.assertEqual(self.mapper.pixel_to_cell(100, 0), (0, 1))
        self.assertEqual(self.mapper.pixel_to_cell(0, 100), (1, 0))

    def test_pixels_outside_the_board_map_to_nothing(self):
        self.assertIsNone(self.mapper.pixel_to_cell(200, 0))
        self.assertIsNone(self.mapper.pixel_to_cell(0, 200))


if __name__ == "__main__":
    unittest.main()
