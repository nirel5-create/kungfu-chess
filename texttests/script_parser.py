from collections import namedtuple

# One line of the script: a verb, its arguments, and -- for `print board` --
# the expected board rows written underneath it (guide S14).
Command = namedtuple("Command", "verb args expected")

# A parsed script: the board section as a grid of tokens, and the command list.
Script = namedtuple("Script", "grid commands")

BOARD_HEADER = "Board:"
COMMANDS_HEADER = "Commands:"

# The DSL's whole vocabulary. A line starting with anything else is not a
# command -- it is expected output belonging to the `print board` above it.
VERBS = ("click", "wait", "print", "jump")


class ScriptParser:
    """Text in, Script out. Owns the script's *syntax* and nothing else: it does
    not know what any command means, does not touch a board, and does not run
    anything.
    """

    def parse(self, text):
        lines = [line.strip() for line in text.splitlines()]
        board_start = lines.index(BOARD_HEADER) + 1
        commands_start = lines.index(COMMANDS_HEADER)
        grid = [line.split() for line in lines[board_start:commands_start] if line]
        commands = []
        for line in lines[commands_start + 1:]:
            if not line:
                continue
            if line.split()[0] in VERBS:
                commands.append(self._command(line))
            elif commands:
                # not a verb -> an expected board row for the print above it
                commands[-1].expected.append(line)
        return Script(grid, commands)

    def _command(self, line):
        parts = line.split()
        args = []
        for p in parts[1:]:
            try:
                args.append(int(p))
            except ValueError:
                args.append(p)
        return Command(parts[0], args, [])
