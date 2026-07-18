"""Integration suite. Every .kfc script runs end to end through the public
command path -- Controller for clicks, GameEngine for time, BoardPrinter for
output -- and its printed board is compared with the expected rows written
inside the script (guide S14: `print board` is the only assertion mechanism).

Adding a case means adding a .kfc file. No Python changes.
"""
import io
import pathlib
import unittest

from model.config import Config
from texttests.script_parser import ScriptParser
from texttests.script_runner import ScriptRunner

SCRIPTS = sorted((pathlib.Path(__file__).parent / "scripts").glob("*.kfc"))


class TestTextScripts(unittest.TestCase):
    def test_scripts_exist(self):
        self.assertTrue(SCRIPTS, "no .kfc scripts found")

    def test_every_script_matches_its_expected_board(self):
        for path in SCRIPTS:
            with self.subTest(script=path.name):
                out = io.StringIO()
                mismatches = ScriptRunner(Config(), out).run(path.read_text())
                for expected, actual in mismatches:
                    self.fail(
                        "{}: printed board does not match the expected rows\n"
                        "expected:\n{}\nactual:\n{}".format(path.name, expected, actual))

    def test_every_script_actually_asserts_something(self):
        # Without this, a script with no expected rows would pass vacuously.
        for path in SCRIPTS:
            with self.subTest(script=path.name):
                script = ScriptParser().parse(path.read_text())
                prints = [c for c in script.commands
                          if c.verb == "print" and c.args == ["board"]]
                self.assertTrue(prints, "script never prints the board")
                for c in prints:
                    self.assertTrue(c.expected, "a print board carries no expected rows")

    def test_a_deliberately_wrong_expectation_is_caught(self):
        # Proves the comparison is real and not vacuously passing.
        script = "Board:\nwR .\n. bK\nCommands:\nprint board\nbK .\n. wR\n"
        mismatches = ScriptRunner(Config(), io.StringIO()).run(script)
        self.assertEqual(len(mismatches), 1)


if __name__ == "__main__":
    unittest.main()
