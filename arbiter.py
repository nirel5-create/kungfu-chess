from motion import Motion
from jump import Jump


class RealTimeArbiter:
    """Owns active-motion and airborne-jump state, and simulated time.
    Board never sees a Motion or Jump; RTA applies board.move/set_piece
    only at arrival."""

    def __init__(self, board, config):
        self._board = board
        self._config = config
        self._clock = 0  # ms
        self._active_motion = None
        self._king_captured = False
        self._airborne = None

    def has_active_motion(self):
        return self._active_motion is not None

    def is_moving(self, cell):
        return self._active_motion is not None and self._active_motion.source == cell

    def has_airborne_piece(self):
        return self._airborne is not None

    def is_airborne(self, cell):
        return self._airborne is not None and self._airborne.cell == cell

    def start_jump(self, piece, cell):
        self._airborne = Jump(piece, cell, self._clock + self._config.jump_ms)

    def start_motion(self, piece, source, destination):
        arrival_time = self._clock + self._config.travel_time(source, destination)
        self._active_motion = Motion(piece, source, destination, arrival_time)

    def advance_time(self, ms):
        self._clock += ms
        self._king_captured = False
        arrivals = self._resolve_motion()
        self._resolve_jump_timeout()
        return arrivals

    def _resolve_motion(self):
        motion = self._active_motion
        if motion is None or self._clock < motion.arrival_time:
            return []
        if self._reverse_if_airborne_enemy(motion):
            self._active_motion = None
            return [motion]
        occupant = self._board.piece_at(*motion.destination)
        self._king_captured = occupant is not None and self._is_king(occupant)
        self._board.move(motion.source, motion.destination)
        promoted = self._config.promotion_target(
            motion.piece, motion.destination[0], self._board
        )
        if promoted is not None:
            self._board.set_piece(motion.destination, promoted)
        self._active_motion = None
        return [motion]

    def _reverse_if_airborne_enemy(self, motion):
        airborne = self._airborne
        if (
            airborne is not None
            and motion.destination == airborne.cell
            and motion.arrival_time <= airborne.end_time
            and not self._config.same_color(motion.piece, airborne.piece)
        ):
            self._king_captured = self._is_king(motion.piece)
            self._board.set_piece(motion.source, self._config.empty)  # arriver vanishes mid-air
            self._airborne = None  # jump resolved via capture; piece lands immediately
            return True
        return False

    def _resolve_jump_timeout(self):
        if self._airborne is not None and self._clock >= self._airborne.end_time:
            self._airborne = None

    def _is_king(self, piece):
        return piece[1] == self._config.king_type

    def king_was_captured(self):
        return self._king_captured
