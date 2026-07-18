import unittest

from model.position import Position



class TestPosition(unittest.TestCase):
    """Guide S6 names these three unit tests explicitly."""

    def test_two_positions_with_the_same_row_and_column_are_equal(self):
        self.assertEqual(Position(2, 3), Position(2, 3))

    def test_two_positions_with_a_different_row_or_column_are_not_equal(self):
        self.assertNotEqual(Position(2, 3), Position(3, 2))
        self.assertNotEqual(Position(2, 3), Position(2, 4))

    def test_positions_produce_a_readable_assertion_failure(self):
        self.assertEqual(repr(Position(2, 3)), "Position(row=2, col=3)")

    def test_position_knows_nothing_about_board_size(self):
        # Bounds belong to Board. Position happily holds a cell off any board.
        self.assertEqual(Position(-5, 99).row, -5)

    def test_a_position_is_interchangeable_with_a_plain_cell_tuple(self):
        # Deliberate: cells were tuples before Position existed, and every
        # existing call site keeps working.
        self.assertEqual(Position(1, 2), (1, 2))
        self.assertEqual({Position(1, 2): "x"}[(1, 2)], "x")

    def test_offset_returns_a_new_position(self):
        self.assertEqual(Position(1, 1).offset(-1, 2), Position(0, 3))


if __name__ == "__main__":
    unittest.main()
