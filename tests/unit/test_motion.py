import unittest

from realtime.jump import Jump
from realtime.motion import Motion



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


if __name__ == "__main__":
    unittest.main()
