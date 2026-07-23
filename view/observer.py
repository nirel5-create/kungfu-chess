"""Watches the game and records captures, score and a moves log.

This is the Observer the instructions ask for. The key design point the mentor
stressed: the observer must NOT sit inside the move logic. Moving a piece is the
hot path of the game; updating a side list is cosmetic and can lag half a second
behind. So the observer never touches the engine or the arbiter. It only looks
at successive GameSnapshots -- "it observes what happens on the board and
updates at its own pace" -- and works out what changed by comparing them.

How a capture is detected: a piece present in the previous snapshot whose cell is
gone (or holds a different-coloured piece) in the new one has been taken. Its
cost is added to the capturing side's score and an entry is appended to the log.

Everything here is pure: no engine, no OpenCV, no clock. It is handed snapshots
and returns updated state, so it is fully testable.
"""

from collections import Counter, namedtuple

CaptureEntry = namedtuple("CaptureEntry", "capturer_color victim_token cost clock_ms")


class GameObserver:
    def __init__(self, config, white_name="Player 1", black_name="Player 2"):
        """config -- used only to read piece costs and colours.
        white_name/black_name -- shown beside each side's score; defaults are
            easy to change in one place, or a caller can pass real names."""
        self._config = config
        self._names = {"w": white_name, "b": black_name}
        self._score = {"w": 0, "b": 0}
        self._log = []
        self._prev = None            # cells occupied at the last observation

    def name_of(self, color):
        return self._names[color]

    def score_of(self, color):
        """A side's running score -- the summed cost of the pieces it has taken."""
        return self._score[color]

    def log(self):
        """The capture log so far, oldest first. A tuple so callers cannot
        mutate the observer's state."""
        return tuple(self._log)

    def observe(self, snapshot, clock_ms=0):
        """Look at a snapshot and fold in anything that changed since the last
        one. Called as often or as rarely as the view likes -- catching up is
        just comparing against the last seen board, so a skipped frame loses
        nothing as long as captures do not reuse a cell within one gap."""
        current = _token_counts(snapshot)
        if self._prev is not None:
            self._record_captures(self._prev, current, clock_ms)
        self._prev = current

    def _record_captures(self, before, after, clock_ms):
        """Any piece that was on the board before and is not now has been
        captured (a move keeps the same token on the board, only at a new cell,
        so it does not count). Comparing token counts finds exactly the pieces
        that left, whatever cell they were on."""
        for token in before:
            lost = before[token] - after.get(token, 0)
            for _ in range(lost):
                self._score_capture(token, clock_ms)

    def _score_capture(self, victim_token, clock_ms):
        victim_color = self._config.color_of(victim_token)
        capturer_color = "b" if victim_color == "w" else "w"
        cost = self._config.cost_of(victim_token)
        self._score[capturer_color] += cost
        self._log.append(CaptureEntry(capturer_color, victim_token, cost, clock_ms))


def _token_counts(snapshot):
    """How many of each token are on the board in this snapshot. Comparing two
    of these across snapshots reveals which pieces left the board -- i.e. were
    captured -- no matter where surviving pieces moved to."""
    return Counter(f"{p.color}{p.kind}" for p in snapshot.pieces)
