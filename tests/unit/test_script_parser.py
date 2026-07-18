import unittest
from texttests.script_parser import ScriptParser




class TestScriptParser(unittest.TestCase):
    """Owns the script syntax only -- it never runs a command."""

    def setUp(self):
        self.parser = ScriptParser()

    def test_splits_the_board_from_the_commands(self):
        script = self.parser.parse(
            "Board:\nwR .\n. bK\nCommands:\nclick 50 50\nwait 1000\nprint board")
        self.assertEqual(script.grid, [["wR", "."], [".", "bK"]])
        self.assertEqual([c.verb for c in script.commands],
                         ["click", "wait", "print"])

    def test_numeric_arguments_are_parsed_as_integers(self):
        script = self.parser.parse("Board:\nwR\nCommands:\nclick 50 150")
        self.assertEqual(script.commands[0].args, [50, 150])

    def test_blank_lines_between_commands_are_ignored(self):
        script = self.parser.parse(
            "Board:\nwR\nCommands:\nclick 50 50\n\n\nwait 1000\n\nprint board")
        self.assertEqual([c.verb for c in script.commands],
                         ["click", "wait", "print"])

    def test_a_stray_line_before_any_command_is_dropped(self):
        script = self.parser.parse("Board:\nwR\nCommands:\n. . .\nprint board")
        self.assertEqual([c.verb for c in script.commands], ["print"])

    def test_non_numeric_arguments_are_left_alone(self):
        script = self.parser.parse("Board:\nwR\nCommands:\nprint board")
        self.assertEqual(script.commands[0].args, ["board"])


if __name__ == "__main__":
    unittest.main()
