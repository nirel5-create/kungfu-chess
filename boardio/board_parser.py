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
