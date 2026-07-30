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

from collections import Counter

from common import topics
from model.snapshot import STATE_JUMPING

# GameEventSource only ever sees snapshots, never a Config -- the same gap
# GameRegistry had for king_type (see common/registry.py). Rather than
# hardcode "P" -> "Q", the mapping is injected, defaulting to Config's own
# default so existing callers that do not care about a custom promotion
# scheme need not pass anything.
_DEFAULT_PROMOTIONS = {"wP": "wQ", "bP": "bQ"}


class GameEventSource:  # pylint: disable=too-few-public-methods
    # A bus subscriber is meant to have exactly one public entry point --
    # the handler it is subscribed with -- so one public method is the
    # design, not a gap; the real logic lives in the private helpers below.
    """Subscribe on_snapshot to topics.SNAPSHOT. Publishes GAME_START once,
    on the very first snapshot; then, for every later snapshot, at most one
    SOUND (game_over beats promotion beats capture beats move -- the most
    informative event for that frame wins, never more than one per frame),
    plus MOVE_LOG/SCORE_UPDATE/GAME_END as their own triggers fire.

    Detects a *transition*, not a state: a piece in flight is reported by
    the engine at its logical (pre-move) cell throughout the whole glide
    (see engine.game.GameEngine.snapshot's own docstring) and only jumps to
    its destination cell in the one snapshot where it arrives. So comparing
    cells between consecutive snapshots already fires exactly once per move,
    with no extra bookkeeping needed to avoid a per-frame stutter.
    """

    def __init__(self, bus, promotions=None):
        """bus -- the Bus to publish on.
        promotions -- {from_token: to_token}, e.g. {"wP": "wQ", "bP": "bQ"};
        defaults to Config's own default. Injected -- see the module-level
        comment on why this cannot be read from a Config directly."""
        self._bus = bus
        self._promotions = promotions if promotions is not None else _DEFAULT_PROMOTIONS
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
        jumped = self._jumped(prev, snapshot)
        game_over_started = (not prev.game_over) and snapshot.game_over

        if game_over_started:
            sound_name = "game_over"
        elif promoted:
            # Promotion outranks capture too: a pawn that captures on the
            # same move it promotes on (arriving on an enemy-occupied
            # promotion-rank cell) makes both `promoted` and `captured`
            # true in the same frame -- promotion is the more informative
            # of the two, so it wins the one sound this frame gets.
            sound_name = "promotion"
        elif captured:
            sound_name = "capture"
        elif moved:
            sound_name = "move"
        elif jumped:
            # Lowest priority: pieces act independently and asynchronously
            # (that is the whole point of "kung-fu" chess), so a jump can
            # land in the same frame as an unrelated piece's move/capture/
            # promotion elsewhere on the board. Those are the more
            # informative event when they coincide.
            sound_name = "jump"
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

    def _promoted(self, prev, curr):
        """Whether some (from_token -> to_token) pair in `promotions`
        happened: from_token's count dropped and to_token's count rose.

        NOT "some cell holds the same color but a different kind than
        before" -- checked against a real engine, that never matches: on
        promotion the pawn arrives at its DESTINATION cell already
        promoted, so the cell and the kind change in the very same
        transition (e.g. ("w","P",1,0) becomes ("w","Q",0,0)). There is no
        snapshot pair where one cell shows both the old and the new kind.
        Token counts are unaffected by which cell anything sits on, which
        is exactly what makes them the right tool here, the same reason
        _captured uses a whole-board count instead of a per-cell one."""
        before = Counter(f"{p.color}{p.kind}" for p in prev.pieces)
        after = Counter(f"{p.color}{p.kind}" for p in curr.pieces)
        for from_token, to_token in self._promotions.items():
            if after.get(from_token, 0) < before.get(from_token, 0) and \
               after.get(to_token, 0) > before.get(to_token, 0):
                return True
        return False

    @staticmethod
    def _jumped(prev, curr):
        """Whether some piece just transitioned INTO the STATE_JUMPING state
        -- the transition, not the state itself: a jump never changes a
        piece's cell (only its state, to STATE_JUMPING for the jump's
        duration and then to STATE_RESTING_SHORT -- see model.snapshot and
        engine.game), so it sits in STATE_JUMPING for many consecutive
        frames while it re-arms. Checking
        the state alone would fire this sound every one of those frames
        instead of once, the same stutter a plain state comparison would
        have caused for promotion (see _promoted's docstring) and moves are
        already protected from by comparing cells rather than pieces.

        A jump's own cell not changing is exactly what makes it usable as
        that piece's identity here: the piece at (row, col) in `curr` is
        the same piece that was at (row, col) in `prev`, if anything was
        there at all."""
        before_state = {(p.row, p.col): p.state for p in prev.pieces}
        return any(
            p.state == STATE_JUMPING and before_state.get((p.row, p.col)) != STATE_JUMPING
            for p in curr.pieces
        )
