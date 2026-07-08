from rules import MoveValidator


class Game:
    """Selection FSM + clock. Knows nothing about storage or I/O."""

    def __init__(self, board, config):
        self._board = board
        self._config = config
        self._validator = MoveValidator(board, config)
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
        if not self._validator.is_legal(src, dst):
            return  # illegal moves are silently ignored
        # Instant settle for iteration 2. When travel_time > 0 this becomes
        # a scheduled event resolved by wait() -- see Config.travel_time.
        if self._config.travel_time(src, dst) <= 0:
            self._board.move(src, dst)

    def wait(self, ms):
        self._clock += ms  # advances the clock; settle scheduled moves here later

    def render(self):
        return self._board.render()