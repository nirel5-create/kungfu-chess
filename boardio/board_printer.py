"""A plain Board-to-text renderer. Despite living in `boardio` next to
`board_parser.py`, this class has no dependency on the VPL script format --
it is the shared "compare a board as text" primitive the project reaches for
whenever something needs to assert board state or serialise it for a
comparison: tests/helpers.py's `render()` wraps it for the bulk of the unit
and integration test suite, tools/fuzz_game.py uses it directly for its
frozen-board and time-slicing-equivalence invariants, and
texttests/script_runner.py uses it to implement `print board`. The name
outlived the assumption that this package was only about the text
protocol."""


class BoardPrinter:
    """Board out, text in. The logical occupancy only -- never an animation
    position (guide S13). Keeping this out of Board is what lets the board's
    internal storage change (a binary representation, say) without touching
    the printed format, and vice versa.
    """

    def print(self, board):
        """-> the board as text, one row per line, cells separated by spaces."""
        return "\n".join(
            " ".join(board.piece_at(r, c) or board.empty_token
                     for c in range(board.cols))
            for r in range(board.rows)
        )
