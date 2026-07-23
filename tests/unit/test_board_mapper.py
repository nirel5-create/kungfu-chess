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


class TestBoardMapperWithFrameOffset(unittest.TestCase):
    """A board drawn with a decorative frame shifts every cell by board_offset,
    so a click must have that offset removed before it maps to a cell."""

    def setUp(self):
        self.config = Config(cell_size=100, board_offset=(10, 20))
        self.board = Board([[".", "."], [".", "."]], self.config)
        self.mapper = BoardMapper(self.board, self.config)

    def test_a_click_inside_the_frame_maps_to_the_first_cell(self):
        # The first cell starts at (10, 20); a click there is cell (0, 0).
        self.assertEqual(self.mapper.pixel_to_cell(10, 20), (0, 0))
        self.assertEqual(self.mapper.pixel_to_cell(109, 119), (0, 0))

    def test_the_offset_shifts_the_cell_boundaries(self):
        # Column boundary is now at 10 + 100 = 110, not 100.
        self.assertEqual(self.mapper.pixel_to_cell(110, 20), (0, 1))
        self.assertEqual(self.mapper.pixel_to_cell(10, 120), (1, 0))


if __name__ == "__main__":
    unittest.main()
