from model.piece import Piece, STATE_IDLE


class Board:
    """Owns the storage. Nobody outside asks how a cell is stored;
    they ask piece_at / move / set_piece. Swap this for a
    bitboard later and no other class changes."""

    def __init__(self, grid, config):
        self._grid = grid  # list[list[str]] -- private
        self._config = config

    @property
    def rows(self):
        return len(self._grid)

    @property
    def cols(self):
        return len(self._grid[0]) if self._grid else 0

    def in_bounds(self, row, col):
        return 0 <= row < self.rows and 0 <= col < self.cols

    def piece_at(self, row, col):
        token = self._grid[row][col]
        return None if token == self._config.empty else token

    def move(self, src, dst):
        (r1, c1), (r2, c2) = src, dst
        self._grid[r2][c2] = self._grid[r1][c1]
        self._grid[r1][c1] = self._config.empty

    def set_piece(self, cell, token):
        row, col = cell
        self._grid[row][col] = token

    @property
    def empty_token(self):
        return self._config.empty

    def piece_object_at(self, row, col, state=None):
        """The piece on this cell as a Piece, or None. The object view of
        piece_at, for callers that need identity rather than a token."""
        token = self.piece_at(row, col)
        if token is None:
            return None
        return Piece.of(token, (row, col), self._config, state=state or STATE_IDLE)

    def pieces(self, states=None):
        """Every piece on the board, as Piece objects. `states` maps a cell to
        that piece's lifecycle state; anything absent is idle."""
        states = states or {}
        return [self.piece_object_at(r, c, states.get((r, c), STATE_IDLE))
                for r in range(self.rows) for c in range(self.cols)
                if self.piece_at(r, c) is not None]
