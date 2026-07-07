import io
import unittest
from unittest.mock import patch

import main


class TestBoardParsing(unittest.TestCase):
    def _run_with(self, fixture):
        with patch("sys.stdin", io.StringIO(fixture)), \
             patch("sys.stdout", new_callable=io.StringIO) as out:
            main.main()
            return out.getvalue()

    def test_print_board_renders_standard_start_position(self):
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
        self.assertEqual(self._run_with(fixture), expected)

    def test_row_width_mismatch_errors(self):
        fixture = (
            "Board:\n"
            "wR wN wB\n"
            "wP wP wP wP\n"
            "Commands:\n"
            "print board\n"
        )
        self.assertEqual(self._run_with(fixture), "ERROR ROW_WIDTH_MISMATCH\n")

    def test_unknown_token_letter_errors(self):
        fixture = (
            "Board:\n"
            "wR wN wZ\n"
            "Commands:\n"
            "print board\n"
        )
        self.assertEqual(self._run_with(fixture), "ERROR UNKNOWN_TOKEN\n")

    def test_unknown_token_case_sensitive(self):
        fixture = (
            "Board:\n"
            "WR wN wB\n"
            "Commands:\n"
            "print board\n"
        )
        self.assertEqual(self._run_with(fixture), "ERROR UNKNOWN_TOKEN\n")

    def test_unknown_token_wrong_color_char(self):
        fixture = (
            "Board:\n"
            "xK . .\n"
            "Commands:\n"
            "print board\n"
        )
        self.assertEqual(self._run_with(fixture), "ERROR UNKNOWN_TOKEN\n")

    def test_row_width_mismatch_takes_precedence_over_unknown_token(self):
        fixture = (
            "Board:\n"
            "wR wN\n"
            "wZ wP wP\n"
            "Commands:\n"
            "print board\n"
        )
        self.assertEqual(self._run_with(fixture), "ERROR ROW_WIDTH_MISMATCH\n")

    def test_no_commands_produces_no_output(self):
        fixture = (
            "Board:\n"
            "wR wN\n"
            "wP wP\n"
            "Commands:\n"
        )
        self.assertEqual(self._run_with(fixture), "")

    def test_multiple_print_commands_repeat_output(self):
        fixture = (
            "Board:\n"
            ". .\n"
            "Commands:\n"
            "print board\n"
            "print board\n"
        )
        self.assertEqual(self._run_with(fixture), ". .\n. .\n")

    def test_unknown_command_is_ignored(self):
        fixture = (
            "Board:\n"
            ". .\n"
            "Commands:\n"
            "do nothing\n"
        )
        self.assertEqual(self._run_with(fixture), "")

    def test_empty_dot_only_board_is_valid(self):
        fixture = (
            "Board:\n"
            ". . .\n"
            ". . .\n"
            "Commands:\n"
            "print board\n"
        )
        self.assertEqual(self._run_with(fixture), ". . .\n. . .\n")


if __name__ == "__main__":
    unittest.main()
