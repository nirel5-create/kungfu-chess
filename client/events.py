"""Derives the events slide 1 needs (sound, move log, score, start/end) from
consecutive GameSnapshots.

The server sends full snapshots, not events (Server_Design.md section 2), so
whoever wants events computes them from state, on the side that is looking.
That is the client -- specifically this module, subscribed to
topics.SNAPSHOT.

What this module owns: turning two consecutive snapshots into the events
slide 1 needs, and publishing them on the bus.
What it does NOT own: playing sound, drawing, sockets, or scoring -- scoring
is GameObserver's job, and GameObserver stays untouched (it is frozen,
in view/, and becomes a bus subscriber by being wired in client.py, not by
being edited).

On the overlap with GameObserver: the observer also notices vanished pieces,
to compute score. This module notices them too, to decide the "capture"
sound name. That is a small duplication -- both walk the same two piece
lists -- but the alternative (routing sound through the observer) would give
the score keeper a second, unrelated job. A two-line diff of duplication is
cheaper than that coupling.
"""

from common import topics


class GameEventSource:  # pylint: disable=too-few-public-methods
    # A bus subscriber is meant to have exactly one public entry point --
    # the handler it is subscribed with -- so one public method is the
    # design, not a gap; the real logic lives in the private helpers below.
    """Subscribe on_snapshot to topics.SNAPSHOT. Publishes GAME_START once,
    on the very first snapshot; then, for every later snapshot, at most one
    SOUND (game_over beats capture beats promotion beats move -- the most
    informative event for that frame wins, never more than one per frame),
    plus MOVE_LOG/SCORE_UPDATE/GAME_END as their own triggers fire.

    Detects a *transition*, not a state: a piece in flight is reported by
    the engine at its logical (pre-move) cell throughout the whole glide
    (see engine.game.GameEngine.snapshot's own docstring) and only jumps to
    its destination cell in the one snapshot where it arrives. So comparing
    cells between consecutive snapshots already fires exactly once per move,
    with no extra bookkeeping needed to avoid a per-frame stutter.
    """

    def __init__(self, bus):
        self._bus = bus
        self._prev = None  # the previous snapshot, or None before the first

    def on_snapshot(self, snapshot):
        """Compare `snapshot` to the previous one and publish whatever
        changed. The first call ever (no previous snapshot) publishes only
        GAME_START."""
        prev = self._prev
        self._prev = snapshot

        if prev is None:
            self._bus.publish(topics.GAME_START, {})
            return

        captured = self._captured(prev, snapshot)
        promoted = self._promoted(prev, snapshot)
        moved = self._moved(prev, snapshot)
        game_over_started = (not prev.game_over) and snapshot.game_over

        if game_over_started:
            sound_name = "game_over"
        elif captured:
            sound_name = "capture"
        elif promoted:
            sound_name = "promotion"
        elif moved:
            sound_name = "move"
        else:
            sound_name = None

        if sound_name is not None:
            self._bus.publish(topics.SOUND, {"name": sound_name})
        if moved or captured:
            self._bus.publish(topics.MOVE_LOG, {})
        if captured:
            self._bus.publish(topics.SCORE_UPDATE, {})
        if game_over_started:
            # This module only ever sees snapshots, never a Config, so it
            # has no king_type to look for (the same fact GameRegistry
            # needed a constructor argument for -- see common/registry.py).
            # Rather than hardcode "K", the winner is reported as not
            # derivable here; server-side, GameRegistry already knows and
            # publishes the real winner on its own bus for whoever needs it.
            self._bus.publish(topics.GAME_END, {})

    @staticmethod
    def _captured(prev, curr):
        """Whether the total piece count dropped. A capture always removes
        exactly one piece from the board, no matter which cell it vanished
        from (the capturing piece moves onto it, so no single cell reliably
        shows "a piece left and none arrived") -- but a per-token-kind count
        (GameObserver's approach, for scoring) is the wrong tool here: a
        promotion changes a piece's kind in place, which also drops the
        pre-promotion token's count without any capture happening. Total
        piece count is immune to that -- a promotion does not change how
        many pieces are on the board, only a capture does."""
        return len(curr.pieces) < len(prev.pieces)

    @staticmethod
    def _moved(prev, curr):
        """Whether the set of occupied cells differs at all -- a plain move
        changes two cells (the piece's old and new cell); a capturing move
        changes one (the capturer's old cell becomes empty; its new cell
        was already occupied, by the victim, both before and after)."""
        before_cells = {(p.row, p.col) for p in prev.pieces}
        after_cells = {(p.row, p.col) for p in curr.pieces}
        return before_cells != after_cells

    @staticmethod
    def _promoted(prev, curr):
        """Whether some cell holds the same color but a different kind than
        it did before -- promotion, by definition, changes a piece in place."""
        before = {(p.row, p.col): (p.color, p.kind) for p in prev.pieces}
        for piece in curr.pieces:
            cell = (piece.row, piece.col)
            if cell in before:
                before_color, before_kind = before[cell]
                if before_color == piece.color and before_kind != piece.kind:
                    return True
        return False
