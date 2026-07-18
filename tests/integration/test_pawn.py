import unittest

from tests.helpers import cell_center, run_fixture, wait_for



class TestPawnMotionIntegration(unittest.TestCase):
    def test_white_pawn_double_step_from_start_arrives(self):
        # 5-row board: white start row = rows-2 = 3, landing on row1
        # (not the promotion edge, row0), so it stays a pawn.
        src_x, src_y = cell_center(1, 3)
        dst_x, dst_y = cell_center(1, 1)
        fixture = (
            "Board:\n. . .\n. . .\n. . .\n. wP .\n. . .\nCommands:\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(2)}\n"
            "print board\n"
        )
        self.assertEqual(
            run_fixture(fixture), ". . .\n. wP .\n. . .\n. . .\n. . .\n"
        )

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

    def test_white_pawn_double_step_from_start_row_lands_on_promotion_edge(self):
        # 4-row board: start row (rows-2=2) and promotion edge (0) are only
        # two rows apart here, so a legal double-step lands exactly on the
        # promotion edge -- both rules must fire together, not conflict.
        src_x, src_y = cell_center(1, 2)
        dst_x, dst_y = cell_center(1, 0)
        fixture = (
            "Board:\n. . .\n. . .\n. wP .\n. . .\nCommands:\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(2)}\n"
            "print board\n"
        )
        self.assertEqual(
            run_fixture(fixture), ". wQ .\n. . .\n. . .\n. . .\n"
        )


if __name__ == "__main__":
    unittest.main()
