import unittest

from boardio.board_parser import BoardParseError, BoardParser
from model.config import Config
from tests.helpers import run_fixture



class TestBoardParser(unittest.TestCase):
    """Guide S17 Iteration 0: BoardParser accepts a rectangular board, rejects
    an inconsistent row length, rejects an illegal token; BoardPrinter
    round-trips a simple board."""

    def setUp(self):
        self.config = Config()
        self.parser = BoardParser(self.config)

    def test_accepts_a_rectangular_board_and_infers_its_size(self):
        board = self.parser.parse("wR . .\n. . .\n. . bK")
        self.assertEqual((board.rows, board.cols), (3, 3))
        self.assertEqual(board.piece_at(0, 0), "wR")
        self.assertEqual(board.piece_at(2, 2), "bK")

    def test_ignores_blank_lines(self):
        board = self.parser.parse("\n\nwR .\n\n. bK\n\n")
        self.assertEqual((board.rows, board.cols), (2, 2))

    def test_rejects_an_inconsistent_row_length(self):
        with self.assertRaises(BoardParseError) as cm:
            self.parser.parse("wR .\nwR . .")
        self.assertEqual(cm.exception.code, "ROW_WIDTH_MISMATCH")

    def test_rejects_an_illegal_piece_token(self):
        with self.assertRaises(BoardParseError) as cm:
            self.parser.parse("wX .\n. .")
        self.assertEqual(cm.exception.code, "UNKNOWN_TOKEN")


class TestBoardValidationAndPrint(unittest.TestCase):
    def test_print_board_renders_start_position(self):
        fixture = (
            "Board:\n"
            "wR wN wB wQ wK wB wN wR\n"
            "wP wP wP wP wP wP wP wP\n"
            ". . . . . . . .\n"
            ". . . . . . . .\n"
            ". . . . . . . .\n"
            ". . . . . . . .\n"
            "bP bP bP bP bP bP bP bP\n"
            "bR bN bB bQ bK bB bN bR\n"
            "Commands:\n"
            "print board\n"
        )
        expected = (
            "wR wN wB wQ wK wB wN wR\n"
            "wP wP wP wP wP wP wP wP\n"
            ". . . . . . . .\n"
            ". . . . . . . .\n"
            ". . . . . . . .\n"
            ". . . . . . . .\n"
            "bP bP bP bP bP bP bP bP\n"
            "bR bN bB bQ bK bB bN bR\n"
        )
        self.assertEqual(run_fixture(fixture), expected)

    def test_leading_space_before_section_marker(self):
        fixture = " Board:\nwK .\n. .\nCommands:\nprint board\n"
        self.assertEqual(run_fixture(fixture), "wK .\n. .\n")

    def test_row_width_mismatch(self):
        fixture = "Board:\nwR wN wB\nwP wP\nCommands:\nprint board\n"
        self.assertEqual(run_fixture(fixture), "ERROR ROW_WIDTH_MISMATCH\n")

    def test_unknown_token_letter(self):
        fixture = "Board:\nwR wN wZ\nCommands:\nprint board\n"
        self.assertEqual(run_fixture(fixture), "ERROR UNKNOWN_TOKEN\n")

    def test_unknown_token_case_sensitive(self):
        fixture = "Board:\nWR wN wB\nCommands:\nprint board\n"
        self.assertEqual(run_fixture(fixture), "ERROR UNKNOWN_TOKEN\n")

    def test_unknown_token_wrong_color_char(self):
        fixture = "Board:\nxK . .\nCommands:\nprint board\n"
        self.assertEqual(run_fixture(fixture), "ERROR UNKNOWN_TOKEN\n")

    def test_width_mismatch_precedes_unknown_token(self):
        fixture = "Board:\nwR wN\nwZ wP wP\nCommands:\nprint board\n"
        self.assertEqual(run_fixture(fixture), "ERROR ROW_WIDTH_MISMATCH\n")

    def test_no_commands_no_output(self):
        fixture = "Board:\nwR wN\nwP wP\nCommands:\n"
        self.assertEqual(run_fixture(fixture), "")

    def test_multiple_print_repeats(self):
        fixture = "Board:\n. .\nCommands:\nprint board\nprint board\n"
        self.assertEqual(run_fixture(fixture), ". .\n. .\n")

    def test_unknown_command_ignored(self):
        fixture = "Board:\n. .\nCommands:\ndo nothing\n"
        self.assertEqual(run_fixture(fixture), "")

    def test_empty_board_valid(self):
        fixture = "Board:\n. . .\n. . .\nCommands:\nprint board\n"
        self.assertEqual(run_fixture(fixture), ". . .\n. . .\n")


if __name__ == "__main__":
    unittest.main()
