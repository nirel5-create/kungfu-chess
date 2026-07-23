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
        # {cell: (end_time, kind)} -- pieces recovering after a move or a jump.
        # While a cell is here it accepts no command, exactly like a moving
        # piece. `kind` is "long" (after a move) or "short" (after a jump), so
        # the view can pick the right rest sprites; the engine treats both the
        # same -- either way the piece is blocked.
        self._resting = {}

    def active_motion_count(self):
        """How many pieces are in flight right now. A query for tests and the
        fuzzer; the engine itself guards per piece via is_moving()."""
        return len(self._active_motions)

    def is_moving(self, cell):
        """The only motion guard: blocks the moving piece, nobody else."""
        return cell in self._active_motions

    def is_resting(self, cell):
        """True while the piece on `cell` is recovering after a move or jump.
        Like is_moving, this blocks only that piece."""
        return cell in self._resting

    def rest_kind(self, cell):
        """"long" (after a move) or "short" (after a jump) for a resting piece,
        or None if it is not resting. The view uses this to pick rest sprites."""
        entry = self._resting.get(cell)
        return entry[1] if entry is not None else None

    def rest_progress(self, cell, duration_ms):
        """How far through its rest the piece on `cell` is, from 0.0 (just
        started) to 1.0 (about to wake), given the rest's full duration. The
        view uses this to draw a filling timer ring. Returns 0.0 if the piece is
        not resting or the duration is zero."""
        entry = self._resting.get(cell)
        if entry is None or duration_ms <= 0:
            return 0.0
        end, _kind = entry
        remaining = end - self._clock
        elapsed = duration_ms - remaining
        return max(0.0, min(1.0, elapsed / duration_ms))

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
        self._clear_finished_rests()
        return arrivals

    def _clear_finished_rests(self):
        """Wake every piece whose rest has elapsed. Done here, in the one place
        that owns the clock, so `wait(a); wait(b)` behaves like `wait(a + b)`."""
        for cell in [c for c, (end, _kind) in self._resting.items()
                     if self._clock >= end]:
            del self._resting[cell]

    def _begin_rest_at(self, cell, event_time, duration_ms, kind):
        """Start a recovery period that began at `event_time` (the arrival or
        jump-end), not at the current clock. Measuring from the event keeps
        `wait(a); wait(b)` identical to `wait(a + b)`: the piece wakes at the
        same absolute time however the waiting was sliced. A zero-length rest
        never marks the piece as resting.

        `kind` is "long" or "short", carried so the view can pick rest sprites.

        If the rest has already fully elapsed within this same tick, the piece
        is simply not marked -- it is already awake."""
        if duration_ms <= 0:
            return
        end = event_time + duration_ms
        if self._clock < end:
            self._resting[cell] = (end, kind)

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
            # A captured piece must not leave a rest behind on its now-empty cell.
            self._resting.pop(motion.destination, None)
        # The mover is leaving its source; any rest recorded there is stale.
        self._resting.pop(motion.source, None)
        self._board.move(motion.source, motion.destination)
        promoted = self._config.promotion_target(
            motion.piece, motion.destination[0], self._board
        )
        if promoted is not None:
            self._board.set_piece(motion.destination, promoted)
        # The piece has arrived; it now recovers before it can move again. The
        # rest is measured from the arrival time so it is wait-additive.
        self._begin_rest_at(motion.destination, motion.arrival_time,
                            self._config.long_rest_ms, "long")

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
            self._resting.pop(motion.source, None)  # and takes any rest with it
            self._airborne = None  # jump resolved via capture; piece lands immediately
            return True
        return False

    def _resolve_jump_timeout(self):
        if self._airborne is not None and self._clock >= self._airborne.end_time:
            # Landed from a jump with no capture -> a short recovery (the mentor:
            # a jump is less tiring than a move, so short_rest, not long_rest).
            # The rest is measured from when the jump *ended*, not from the
            # current clock, so a single big wait matches many small ones.
            self._begin_rest_at(self._airborne.cell, self._airborne.end_time,
                                self._config.short_rest_ms, "short")
            self._airborne = None

    def king_was_captured(self):
        return self._king_captured
