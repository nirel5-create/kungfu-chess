from model.position import Position


class BoardMapper:
    """Coordinate adapter: screen pixels in, board cells out. The only place
    that knows a cell is Config.cell_size pixels wide.

    Owns pixel-to-cell mapping. Owns nothing else -- not selection, not
    legality, not timing. Read-only with respect to the board.
    """

    def __init__(self, board, config):
        self._board = board
        self._config = config

    def pixel_to_cell(self, x, y):
        """-> Position under (x, y), or None if that is off the board (guide S20).

        Subtracts the board's frame offset first, so a click is measured from
        the first cell, not the image edge -- the mirror of how the snapshot
        adds the offset when placing pieces."""
        off_x, off_y = self._config.board_offset
        row = (y - off_y) // self._config.cell_size
        col = (x - off_x) // self._config.cell_size
        if not self._board.in_bounds(row, col):
            return None
        return Position(row, col)
