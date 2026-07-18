from realtime.arbiter import RealTimeArbiter
from model.snapshot import GameSnapshot, PieceView, STATE_IDLE, STATE_MOVING
from engine.results import (
    MoveResult, ACCEPTED, REASON_GAME_OVER, REASON_MOTION_IN_PROGRESS, REASON_AIRBORNE,
)
from rules.rules import RuleEngine


class GameEngine:
    """Application service. Applies the guards that are about the *game* --
    is it over, is this piece already busy -- then delegates: legality to
    MoveValidator, time and motion to RealTimeArbiter.

    Owns the game-over flag and nothing else. It holds no pixels, no
    selection, no rendering, and no piece-specific movement logic.

    Collaborators may be injected; by default it composes the real ones. That
    is what lets a test hand it a fake arbiter instead of monkeypatching.
    """

    # Re-exported so callers can compare against GameEngine.REASON_* without
    # importing the results module.
    REASON_GAME_OVER = REASON_GAME_OVER
    REASON_MOTION_IN_PROGRESS = REASON_MOTION_IN_PROGRESS
    REASON_AIRBORNE = REASON_AIRBORNE

    def __init__(self, board, config, validator=None, arbiter=None):
        self._board = board
        self._config = config
        self._validator = validator or RuleEngine(board, config)
        self._rta = arbiter or RealTimeArbiter(board, config)
        self._game_over = False

    @property
    def game_over(self):
        return self._game_over

    def request_move(self, src, dst):
        """-> MoveResult (guide S9). reason is always set: "ok" when accepted,
        an application-level reason when this layer refuses, or the rule-level
        reason copied straight from MoveValidation."""
        if self._game_over:
            return MoveResult(False, REASON_GAME_OVER)  # board untouched
        if self._rta.is_moving(src):
            return MoveResult(False, REASON_MOTION_IN_PROGRESS)  # only that piece
        if self._rta.is_airborne(src):
            return MoveResult(False, REASON_AIRBORNE)  # rule 2: a jumper stays put
        validation = self._validator.validate_move(src, dst)
        if not validation.is_valid:
            return MoveResult(False, validation.reason)  # rule-level reason, verbatim
        piece = self._board.piece_at(*src)
        self._rta.start_motion(piece, src, dst)
        return ACCEPTED

    def request_jump(self, cell):
        """Send the piece on `cell` airborne. The six jump rules:
        1. A jump lasts Config.jump_ms.
        2. The jumping piece stays on its logical cell -- it does not move.
        3. If an enemy arrives at the airborne cell during the window, the
           airborne piece captures it (reversal of normal arrival) --
           see RealTimeArbiter._reverse_if_airborne_enemy.
        4. If no enemy arrives, the piece lands normally when the window ends.
        5. A piece that is currently moving cannot jump (checked here).
        6. A captured/empty cell cannot jump (checked here).
        """
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
        if self._game_over:
            return  # the game ended: time stops, pieces still in flight never land
        self._rta.advance_time(ms)
        if self._rta.king_was_captured():
            self._game_over = True

    def snapshot(self, selected_cell=None):
        """-> GameSnapshot (guide S20). A read-only view for the renderer: it
        never receives the live Board or Piece objects (guide S19).

        A piece in flight is reported on its *logical* cell -- the board only
        changes on arrival -- but with an interpolated pixel position, which is
        what lets the renderer draw it between cells.
        """
        cell = self._config.cell_size
        views = []
        for row in range(self._board.rows):
            for col in range(self._board.cols):
                token = self._board.piece_at(row, col)
                if token is None:
                    continue
                motion = self._rta.motion_from((row, col))
                if motion is None:
                    x, y, state = col * cell, row * cell, STATE_IDLE
                else:
                    x, y = self._rta.interpolate(motion, cell)
                    state = STATE_MOVING
                views.append(PieceView(
                    kind=self._config.type_of(token),
                    color=self._config.color_of(token),
                    row=row, col=col, x=x, y=y, state=state))
        return GameSnapshot(
            board_width=self._board.cols, board_height=self._board.rows,
            cell_size=cell, pieces=tuple(views),
            selected_cell=selected_cell, game_over=self._game_over)
