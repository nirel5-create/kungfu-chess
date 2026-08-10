"""The text-to-Board half of `boardio` (see board_printer.py's own module
docstring for the other half). Reads the grid at the top of a VPL script
into a real Board -- texttests/script_runner.py's own starting position --
and, together with BoardPrinter, round-trips a board as text for
tests/unit/test_board_printer.py. Not dead VPL leftovers: script_runner.py
genuinely parses every script's board section through this class, so it is
load-bearing for the script-driven test DSL tests/helpers.py's
`run_fixture()` and the tests/integration/*.kfc suite both depend on."""
from model.board import Board


class BoardParseError(Exception):
    """Raised when the text does not describe a board. Carries a stable,
    machine-readable code so callers can map it to their own output."""

    ROW_WIDTH_MISMATCH = "ROW_WIDTH_MISMATCH"
    UNKNOWN_TOKEN = "UNKNOWN_TOKEN"

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class BoardParser:
    """Text in, Board out. A shared text-I/O adapter, not a test helper: the
    application and the test runner parse boards the same way (guide S13).

    Owns the textual format and nothing else -- no movement rules, no command
    execution, no rendering.
    """

    def __init__(self, config):
        self._config = config

    def parse(self, text):
        """-> Board. Raises BoardParseError with a stable code.

        The board's size is inferred from the text (guide S3.1): every row must
        have the same number of cells, and every token must be one Config knows.
        """
        rows = [line.split() for line in text.strip().splitlines() if line.strip()]
        return self.parse_grid(rows)

    def parse_grid(self, grid):
        widths = {len(row) for row in grid}
        if len(widths) > 1:
            raise BoardParseError(BoardParseError.ROW_WIDTH_MISMATCH)
        for row in grid:
            for token in row:
                if not self._config.is_valid_token(token):
                    raise BoardParseError(BoardParseError.UNKNOWN_TOKEN)
        return Board(grid, self._config)
