import io
import unittest
from unittest.mock import patch

import main


class TestEcho(unittest.TestCase):
    def _run_with(self, fixture):
        with patch("sys.stdin", io.StringIO(fixture)), \
             patch("sys.stdout", new_callable=io.StringIO) as out:
            main.main()
            return out.getvalue()

    def test_echoes_simple_board_fixture(self):
        fixture = "board\n........\n........\n"
        self.assertEqual(self._run_with(fixture), fixture)

    def test_echoes_empty_input(self):
        self.assertEqual(self._run_with(""), "")

    def test_preserves_trailing_newline(self):
        fixture = "board\nWK......\n"
        self.assertEqual(self._run_with(fixture), fixture)

    def test_preserves_missing_trailing_newline(self):
        fixture = "board\nBR......"
        self.assertEqual(self._run_with(fixture), fixture)


if __name__ == "__main__":
    unittest.main()
