# Repo: https://github.com/nirel5-create/kungfu-chess
import sys

# Protocol output strings (single source of truth, never inline magic strings).
ERROR_ROW_WIDTH = "ERROR ROW_WIDTH_MISMATCH"
ERROR_UNKNOWN_TOKEN = "ERROR UNKNOWN_TOKEN"


class Config:
    """All tunable rules live here. Nothing about *what* pieces exist,
    how big a cell is, or how a move settles is hardcoded in the logic."""

    def __init__(
        self,
        cell_size=100,
        colors=("w", "b"),
        piece_types=("K", "Q", "R", "B", "N", "P"),
        empty=".",
    ):
        self.cell_size = cell_size
        self.colors = colors
        self.piece_types = piece_types
        self.empty = empty

    def is_valid_token(self, token):
        if token == self.empty:
            return True
        return (
            len(token) == 2
            and token[0] in self.colors
            and token[1] in self.piece_types
        )

    def same_color(self, token_a, token_b):
        return token_a[0] == token_b[0]

    def travel_time(self, src, dst):
        # Iteration 2: no numbers are given, so moves are instant.
        # When travel time arrives, return the duration here and the
        # settle machinery in Game already handles the rest.
        return 0


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


class Game:
    """Selection FSM + clock. Knows nothing about storage or I/O."""

    def __init__(self, board, config):
        self._board = board
        self._config = config
        self._selection = None  # (row, col) or None
        self._clock = 0  # ms

    def _pixel_to_cell(self, x, y):
        return y // self._config.cell_size, x // self._config.cell_size

    def click(self, x, y):
        row, col = self._pixel_to_cell(x, y)
        if not self._board.in_bounds(row, col):
            return  # outside the board -> ignored
        target = self._board.piece_at(row, col)
        if self._selection is None:
            if target is not None:
                self._selection = (row, col)  # select
            return  # empty cell with no selection -> ignored
        selected = self._board.piece_at(*self._selection)
        if target is not None and self._config.same_color(target, selected):
            self._selection = (row, col)  # replace selection
            return
        self._request_move(self._selection, (row, col))
        self._selection = None

    def _request_move(self, src, dst):
        # Instant settle for iteration 2. When travel_time > 0 this becomes
        # a scheduled event resolved by wait() -- see Config.travel_time.
        if self._config.travel_time(src, dst) <= 0:
            self._board.move(src, dst)

    def wait(self, ms):
        self._clock += ms  # advances the clock; settle scheduled moves here later

    def render(self):
        return self._board.render()


def parse_sections(lines):
    lines = [line.strip() for line in lines]
    board_start = lines.index("Board:") + 1
    commands_start = lines.index("Commands:")
    grid = [line.split() for line in lines[board_start:commands_start] if line]
    commands = [line for line in lines[commands_start + 1:] if line]
    return grid, commands


def validate_board(grid, config):
    widths = {len(row) for row in grid}
    if len(widths) > 1:
        return ERROR_ROW_WIDTH
    for row in grid:
        for token in row:
            if not config.is_valid_token(token):
                return ERROR_UNKNOWN_TOKEN
    return None


def dispatch(game, command, out):
    parts = command.split()
    if command == "print board":
        print(game.render(), file=out)
    elif parts[0] == "click" and len(parts) == 3:
        game.click(int(parts[1]), int(parts[2]))
    elif parts[0] == "wait" and len(parts) == 2:
        game.wait(int(parts[1]))
    # anything else -> ignored


def run(inp, out):
    lines = inp.read().splitlines()
    grid, commands = parse_sections(lines)
    config = Config()
    error = validate_board(grid, config)
    if error:
        print(error, file=out)
        return
    game = Game(Board(grid, config), config)
    for command in commands:
        dispatch(game, command, out)


if __name__ == "__main__":
    run(sys.stdin, sys.stdout)  # pragma: no cover