from motion import Motion


class RealTimeArbiter:
    """Owns active-motion state and simulated time. Board never sees a
    Motion; RTA applies board.move only at arrival."""

    def __init__(self, board, config):
        self._board = board
        self._config = config
        self._clock = 0  # ms
        self._active_motion = None
        self._king_captured = False

    def has_active_motion(self):
        return self._active_motion is not None

    def start_motion(self, piece, source, destination):
        arrival_time = self._clock + self._config.travel_time(source, destination)
        self._active_motion = Motion(piece, source, destination, arrival_time)

    def advance_time(self, ms):
        self._clock += ms
        motion = self._active_motion
        self._king_captured = False
        if motion is not None and self._clock >= motion.arrival_time:
            occupant = self._board.piece_at(*motion.destination)
            self._king_captured = (
                occupant is not None and occupant[1] == self._config.king_type
            )
            self._board.move(motion.source, motion.destination)
            self._active_motion = None
            return [motion]
        return []

    def king_was_captured(self):
        return self._king_captured
