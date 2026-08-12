"""Derives the events the UI needs (sound, move log, score, start/end) from
consecutive GameSnapshots, published on the bus.

The server sends full snapshots, not events, so this module computes events
client-side by diffing each snapshot against the one before it.

Sound selection and GameObserver's score tracking both scan the same two
piece lists for vanished pieces. That duplication is deliberate: routing
sound through GameObserver would give the score keeper a second, unrelated
job. A few lines of duplication are cheaper than that coupling.
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
    """Subscribes on_snapshot to topics.SNAPSHOT: publishes GAME_START once,
    then at most one SOUND per snapshot (game_over beats promotion beats
    capture beats move), plus MOVE_LOG/SCORE_UPDATE/GAME_END as triggered.
    Diffs consecutive snapshots rather than piece state directly, since a
    piece in flight sits at its pre-move cell until it lands."""

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
        """Whether the total piece count dropped -- the capture signal. A
        per-token-kind count (GameObserver's approach) would be wrong here:
        promotion also drops its pre-promotion token's count without a
        capture happening. Total piece count is immune, since promotion
        never changes how many pieces are on the board."""
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
        Token counts, not "a cell's kind changed", because a promoted pawn
        already shows its new kind at its new cell in the same snapshot --
        no pair of snapshots ever shows one cell holding both kinds."""
        before = Counter(f"{p.color}{p.kind}" for p in prev.pieces)
        after = Counter(f"{p.color}{p.kind}" for p in curr.pieces)
        for from_token, to_token in self._promotions.items():
            if after.get(from_token, 0) < before.get(from_token, 0) and \
               after.get(to_token, 0) > before.get(to_token, 0):
                return True
        return False

    @staticmethod
    def _jumped(prev, curr):
        """Whether some piece just transitioned into STATE_JUMPING -- checked
        as a transition, not the state itself, since a piece sits in
        STATE_JUMPING for many frames while it re-arms, and a plain state
        check would fire every frame. A jump never moves a piece's cell, so
        (row, col) reliably identifies the same piece across snapshots."""
        before_state = {(p.row, p.col): p.state for p in prev.pieces}
        return any(
            p.state == STATE_JUMPING and before_state.get((p.row, p.col)) != STATE_JUMPING
            for p in curr.pieces
        )
