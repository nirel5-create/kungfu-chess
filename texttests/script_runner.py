from boardio.board_parser import BoardParser, BoardParseError
from boardio.board_printer import BoardPrinter
from engine.game import GameEngine
from input.board_mapper import BoardMapper
from input.controller import Controller
from texttests.script_parser import ScriptParser

# Protocol output strings. Single source of truth -- never inline.
ERROR_PREFIX = "ERROR "
ERROR_ROW_WIDTH = ERROR_PREFIX + BoardParseError.ROW_WIDTH_MISMATCH
ERROR_UNKNOWN_TOKEN = ERROR_PREFIX + BoardParseError.UNKNOWN_TOKEN


class ScriptRunner:
    """Drives the public command path exactly as a user would (guide S15): a
    click goes through the Controller, a wait goes through the GameEngine, and
    `print board` goes through the BoardPrinter.

    It never bypasses those to touch Board directly -- doing so would make the
    test stop proving that the real command path works.

    It owns no game logic and no text formats: parsing and printing are
    delegated to the shared adapters.
    """

    def __init__(self, config, out):
        self._config = config
        self._out = out
        self._parser = ScriptParser()
        self._board_parser = BoardParser(config)
        self._printer = BoardPrinter()

    def run(self, text):
        """Runs the script and prints what it prints.

        -> a list of mismatches: for every `print board` that carried expected
        rows, a (expected, actual) pair when they differ. Empty means the script
        passed. Printing and checking are the same code path, so an integration
        test proves the very thing a user sees.
        """
        script = self._parser.parse(text)
        try:
            board = self._board_parser.parse_grid(script.grid)
        except BoardParseError as e:
            print(ERROR_PREFIX + e.code, file=self._out)
            return []
        engine = GameEngine(board, self._config)
        controller = Controller(engine, BoardMapper(board, self._config),
                                board, self._config)
        mismatches = []
        for command in script.commands:
            self._dispatch(board, engine, controller, command, mismatches)
        return mismatches

    def _dispatch(self, board, engine, controller, command, mismatches):
        verb, args = command.verb, command.args
        if verb == "print" and args == ["board"]:
            actual = self._printer.print(board)
            print(actual, file=self._out)
            if command.expected:
                expected = "\n".join(command.expected)
                if expected != actual:
                    mismatches.append((expected, actual))
        elif verb == "click" and len(args) == 2:
            controller.click(*args)
        elif verb == "wait" and len(args) == 1:
            engine.wait(args[0])
        elif verb == "jump" and len(args) == 2:
            controller.jump(*args)
        # anything else -> ignored
