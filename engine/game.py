from realtime.arbiter import RealTimeArbiter
from rules.rules import MoveValidator


class Game:
    """Selection FSM plus application-level guards (game-over, jump
    eligibility). Knows nothing about storage, timing, or I/O --
    RealTimeArbiter owns motion/jump state and simulated time."""

    REASON_GAME_OVER = "game_over"
    REASON_MOTION_IN_PROGRESS = "motion_in_progress"
    REASON_AIRBORNE = "airborne"

    def __init__(self, board, config):
        self._board = board
        self._config = config
        self._validator = MoveValidator(board, config)
        self._rta = RealTimeArbiter(board, config)
        self._selection = None  # (row, col) or None
        self._game_over = False

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
        if self._game_over:
            return self.REASON_GAME_OVER  # board untouched, nothing else checked
        if self._rta.has_active_motion():
            return self.REASON_MOTION_IN_PROGRESS  # board untouched, no motion started
        if self._rta.is_airborne(src):
            return self.REASON_AIRBORNE  # protects rule 2: a jumping piece does not move
        if not self._validator.is_legal(src, dst):
            return None  # illegal moves are silently ignored
        piece = self._board.piece_at(*src)
        self._rta.start_motion(piece, src, dst)
        return None

    def jump(self, x, y):
        """Send the piece at (x, y) airborne. The six jump rules:
        1. A jump lasts Config.jump_ms.
        2. The jumping piece stays on its logical cell -- it does not move.
        3. If an enemy arrives at the airborne cell during the window, the
           airborne piece captures it (reversal of normal arrival) --
           see RealTimeArbiter._reverse_if_airborne_enemy.
        4. If no enemy arrives, the piece lands normally when the window ends.
        5. A piece that is currently moving cannot jump (checked here).
        6. A captured/empty cell cannot jump (checked here).
        """
        cell = self._pixel_to_cell(x, y)
        if not self._board.in_bounds(*cell):
            return  # outside the board -> ignored, mirrors click()
        if self._game_over:
            return  # board/RTA untouched once the game has ended
        piece = self._board.piece_at(*cell)
        if piece is None:
            return  # rule 6: nothing there to jump (captured/empty cell)
        if self._rta.is_moving(cell):
            return  # rule 5: a moving piece cannot jump
        if self._rta.has_airborne_piece():
            return  # one active jump at a time (mirrors motion_in_progress)
        self._rta.start_jump(piece, cell)

    def wait(self, ms):
        self._rta.advance_time(ms)
        if self._rta.king_was_captured():
            self._game_over = True

    def render(self):
        return self._board.render()