import unittest

from tests.helpers import CFG, cell_center, run_fixture, wait_for



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

    def test_jump_with_no_arrival_lands_then_rests_then_can_move(self):
        # After a jump lands (no capture) the piece is in short_rest and cannot
        # move until it elapses -- shorter than long_rest, per the mentor.
        jump_x, jump_y = cell_center(0, 0)
        src_x, src_y = cell_center(0, 0)
        dst_x, dst_y = cell_center(1, 0)
        fixture = (
            "Board:\nwK . .\nCommands:\n"
            f"jump {jump_x} {jump_y}\n"
            f"wait {wait_for(1)}\n"
            f"wait {CFG.short_rest_ms}\n"      # recover from the jump
            f"click {src_x} {src_y}\n"
            f"click {dst_x} {dst_y}\n"
            f"wait {wait_for(1)}\n"
            "print board\n"
        )
        self.assertEqual(run_fixture(fixture), ". wK .\n")


if __name__ == "__main__":
    unittest.main()
