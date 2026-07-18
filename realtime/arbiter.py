from realtime.motion import Motion
from realtime.jump import Jump


class RealTimeArbiter:
    """Owns active-motion and airborne-jump state, and simulated time.
    Board never sees a Motion or Jump; RTA applies board.move/set_piece
    only at arrival.

    Motions run concurrently: any number of pieces may be in flight at
    once. A motion is keyed by its source cell, which is a stable key
    because a moving piece stays logically on its source cell until it
    arrives -- the board only changes at arrival.
    """

    def __init__(self, board, config):
        self._board = board
        self._config = config
        self._clock = 0  # ms
        self._active_motions = {}  # {source_cell: Motion}
        self._king_captured = False
        self._airborne = None

    def has_active_motion(self):
        """True if any piece is in flight. Kept for API compatibility;
        the engine guards per piece via is_moving()."""
        return bool(self._active_motions)

    def active_motion_count(self):
        return len(self._active_motions)

    def is_moving(self, cell):
        """The only motion guard: blocks the moving piece, nobody else."""
        return cell in self._active_motions

    def motion_from(self, cell):
        """The motion that started on `cell`, or None. Read-only."""
        return self._active_motions.get(cell)

    def interpolate(self, motion, cell_size):
        """-> (x, y) in pixels for a piece in flight. The arbiter owns the
        clock, so it is the only place that can answer where a piece is *now*.
        Returns pixels rather than a fraction so no caller has to redo the
        timing maths; it still holds no opinion about how anything is drawn."""
        span = self._config.travel_time(motion.source, motion.destination)
        started = motion.arrival_time - span
        p = 1.0 if span == 0 else min(1.0, max(0.0, (self._clock - started) / span))
        sr, sc = motion.source
        dr, dc = motion.destination
        return ((sc + (dc - sc) * p) * cell_size,
                (sr + (dr - sr) * p) * cell_size)

    def has_airborne_piece(self):
        return self._airborne is not None

    def is_airborne(self, cell):
        return self._airborne is not None and self._airborne.cell == cell

    def start_jump(self, piece, cell):
        self._airborne = Jump(piece, cell, self._clock + self._config.jump_ms)

    def start_motion(self, piece, source, destination):
        arrival_time = self._clock + self._config.travel_time(source, destination)
        self._active_motions[source] = Motion(piece, source, destination, arrival_time)

    def advance_time(self, ms):
        self._clock += ms
        self._king_captured = False
        arrivals = self._resolve_motions()
        self._resolve_jump_timeout()
        return arrivals

    def _due_motions(self):
        """Motions that have landed, earliest first. The tie-break on source
        keeps the order deterministic when two pieces land in the same
        millisecond."""
        due = [m for m in self._active_motions.values()
               if self._clock >= m.arrival_time]
        return sorted(due, key=lambda m: (m.arrival_time, m.source))

    def _resolve_motions(self):
        """Resolve every landing in chronological order. Order is what
        implements the collision rule: the earlier piece lands first, so a
        later arriver finds it sitting there and captures it.

        A king capture stops the loop: nothing lands after the game has been
        decided. Stopping here rather than in the caller is what keeps
        `wait(a); wait(b)` identical to `wait(a + b)` (Design Guide S17,
        Iteration 5)."""
        arrivals = []
        for motion in self._due_motions():
            self._active_motions.pop(motion.source, None)
            self._resolve_one(motion)
            arrivals.append(motion)
            if self._king_captured:
                break
        return arrivals

    def _resolve_one(self, motion):
        if self._reverse_if_airborne_enemy(motion):
            return
        occupant = self._board.piece_at(*motion.destination)
        if occupant is not None and self._config.same_color(occupant, motion.piece):
            # A friendly piece got here first -- only reachable once motions run
            # concurrently. Cancel rather than clobber: the mover stays put and
            # the board is left untouched.
            return
        if occupant is not None:
            if self._config.is_king(occupant):
                self._king_captured = True
            # The victim may itself have been in flight. Its motion is keyed by
            # this cell, because a moving piece stays on its source until arrival.
            # Drop it: a dead piece must not go on to complete its trip.
            self._active_motions.pop(motion.destination, None)
        self._board.move(motion.source, motion.destination)
        promoted = self._config.promotion_target(
            motion.piece, motion.destination[0], self._board
        )
        if promoted is not None:
            self._board.set_piece(motion.destination, promoted)

    def _reverse_if_airborne_enemy(self, motion):
        airborne = self._airborne
        if (
            airborne is not None
            and motion.destination == airborne.cell
            and motion.arrival_time <= airborne.end_time
            and not self._config.same_color(motion.piece, airborne.piece)
        ):
            if self._config.is_king(motion.piece):
                self._king_captured = True
            self._board.set_piece(motion.source, self._config.empty)  # arriver vanishes mid-air
            self._airborne = None  # jump resolved via capture; piece lands immediately
            return True
        return False

    def _resolve_jump_timeout(self):
        if self._airborne is not None and self._clock >= self._airborne.end_time:
            self._airborne = None

    def king_was_captured(self):
        return self._king_captured
