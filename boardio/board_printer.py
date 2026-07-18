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
