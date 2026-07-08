class Board:
    """Owns the storage. Nobody outside asks how a cell is stored;
    they ask piece_at / move / render. Swap this for a bitboard later
    and no other class changes."""

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

    def render(self):
        return "\n".join(" ".join(row) for row in self._grid)