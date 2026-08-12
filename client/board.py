"""Controller and BoardMapper's read-only view of "the board", backed by
whatever snapshot the server most recently sent -- never an independent
model.Board.
"""


class _SnapshotBoard:  # pragma: no cover
    """Read-only piece_at/in_bounds backed by `link`'s latest snapshot,
    never a locally maintained copy, since only the server validates moves.
    Controller.click() reads it twice per click, and a new snapshot can
    arrive in between; accepted deliberately, since the server re-validates
    every move anyway -- a torn read risks at most a stale selection."""

    def __init__(self, link):
        self._link = link

    def piece_at(self, row, col):
        """-> the token at (row, col) THIS CLIENT may select, or None -- for
        an empty cell, an opponent's piece, or any cell if unassigned/a
        viewer. Hiding opponent pieces behind None makes them look empty to
        Controller (frozen, unchanged) so they can't be selected; captures
        still reach the server via Controller's existing move-request path."""
        snapshot = self._link.snapshot()
        color = self._link.color()
        if snapshot is None or color is None or color == "viewer":
            return None
        for piece in snapshot.pieces:
            if piece.row == row and piece.col == col:
                return f"{piece.color}{piece.kind}" if piece.color == color else None
        return None

    def in_bounds(self, row, col):
        """-> whether (row, col) is on the board, per the latest snapshot's
        own dimensions -- False before the first snapshot arrives, since
        there is nothing to click yet either."""
        snapshot = self._link.snapshot()
        if snapshot is None:
            return False
        return 0 <= row < snapshot.board_height and 0 <= col < snapshot.board_width
