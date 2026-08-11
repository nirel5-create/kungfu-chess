"""Controller and BoardMapper's read-only view of "the board", backed by
whatever snapshot the server most recently sent -- never an independent
model.Board.
"""


class _SnapshotBoard:  # pragma: no cover
    """The server is the single source of truth for board state: every move
    is validated and applied there, never locally. So the client must not
    keep its own Board that it updates (or fails to update) itself -- any
    such copy is only ever a guess about server state and will drift the
    moment a move lands. Instead every call here reads whatever snapshot
    `link` most recently received, so a selection or move decision is
    always made against the position the server just reported.

    Exposes only the two members Controller and BoardMapper actually read
    from a Board: piece_at(row, col) and in_bounds(row, col). Both report
    "nothing here" / "out of bounds" before the first snapshot arrives,
    which matches the draw loop drawing nothing until then -- there is
    nothing to click yet either.

    Controller.click() calls piece_at() up to twice per click (once for the
    clicked cell, once for the already-selected cell), and the network
    thread can overwrite `link`'s snapshot between those two calls -- new
    ones arrive roughly every 30ms. So the two reads can, in principle, see
    two different snapshots. This is accepted deliberately rather than
    papered over (e.g. by snapshotting once per click): the window is a few
    milliseconds, and any decision made from a torn pair of reads only ever
    produces a `move`/`jump` message, which the server -- the actual
    authority on legality -- will simply refuse if it turns out to be
    illegal. Nothing here can corrupt game state, only at worst pick a
    slightly stale selection for one click.

    piece_at also hides any piece that does not belong to this client's own
    assigned color (see piece_at's docstring for why that alone is enough to
    stop the opponent's pieces from lighting up on click, with zero changes
    to the frozen Controller).
    """

    def __init__(self, link):
        self._link = link

    def piece_at(self, row, col):
        """-> the token at (row, col), or None if there is nothing here THIS
        CLIENT may select -- which includes a cell that is merely empty, a
        cell holding the opponent's piece, and every cell at all if this
        client is a "viewer" or has no assigned color yet.

        Controller (frozen) only ever calls piece_at to decide selection: no
        piece there means nothing to select. So hiding an opponent's piece
        behind None makes it look exactly like an empty cell to Controller,
        which is enough on its own to stop it from ever being selected --
        Controller itself needed no change. Captures still work: clicking a
        cell that reads as "empty" while a piece is already selected is
        precisely Controller's request_move branch, so a capture of a
        hidden opponent piece is still sent to the server as a move, which
        the server -- the actual authority on legality -- applies or
        refuses. Rendering is unaffected by any of this: Renderer paints
        straight from the snapshot, never through this view, so the
        opponent's pieces are always drawn; only click-driven selection is
        blind to them.

        Before the server's `assigned` message arrives, this client owns no
        color yet, so every cell reads as empty rather than guessing -- the
        same treatment as being assigned "viewer"."""
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
