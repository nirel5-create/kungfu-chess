import unittest

from tests.helpers import cell_center, run_fixture, wait_for



class TestJumpIntegration(unittest.TestCase):
    def test_jump_reversal_matches_vpl_test_2(self):
        jump_x, jump_y = cell_center(0, 0)
        src_x, src_y = cell_center(1, 0)
        dst_x, dst_y = cell_center(0, 0)
        fixture = (
            "Board:\nwK bR .\nCommands:\n"
            f"jump {jump_x} {jump_y}\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(1)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), "wK . .\n")

    def test_jump_with_no_arrival_lands_and_can_move_again(self):
        jump_x, jump_y = cell_center(0, 0)
        src_x, src_y = cell_center(0, 0)
        dst_x, dst_y = cell_center(1, 0)
        fixture = (
            "Board:\nwK . .\nCommands:\n"
            f"jump {jump_x} {jump_y}\n"
            f"wait {wait_for(1)}\n"
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(1)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". wK .\n")


if __name__ == "__main__":
    unittest.main()
