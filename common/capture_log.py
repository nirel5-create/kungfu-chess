"""Server-side clone of view.observer.GameObserver's pure capture-detection
algorithm: compare token counts between two consecutive GameSnapshots -- a
piece present before and gone now was captured, whatever cell it vanished
from -- and score it to the side that took it.

Why a clone and not an import: view/ is the client's OpenCV rendering
stack and is deliberately not part of the server's Docker image, so
`from view.observer import GameObserver` breaks the server in the
container with ModuleNotFoundError at startup. view/observer.py is also
frozen and cannot be moved somewhere both sides can import from.

Deliberately narrower than GameObserver: no name_of, no names at all.
server.py computes display names separately, fresh from
GameRegistry.seats every broadcast, since a username can change after
construction -- GameObserver's own names are fixed with no setter.
"""

from collections import Counter

from common.protocol import CaptureEntry


class CaptureLog:
    """Tracks captures and each side's running score across consecutive
    GameSnapshots -- a server-side clone of view.observer.GameObserver,
    kept independent of the client's rendering stack."""

    def __init__(self, config):
        """config -- used only to read piece costs and colours (the same
        role it plays for GameObserver)."""
        self._config = config
        self._score = {"w": 0, "b": 0}
        self._log = []
        self._prev = None  # token counts at the last observation

    def score_of(self, color):
        """A side's running score -- the summed cost of the pieces it has
        taken."""
        return self._score[color]

    def log(self):
        """The capture log so far, oldest first. A tuple so callers
        cannot mutate this object's state."""
        return tuple(self._log)

    def observe(self, snapshot, clock_ms=0):
        """Look at `snapshot` and fold in anything that changed since the
        last one. The first call ever (no previous snapshot) never scores
        anything -- there is nothing yet to compare against."""
        current = _token_counts(snapshot)
        if self._prev is not None:
            self._record_captures(self._prev, current, clock_ms)
        self._prev = current

    def _record_captures(self, before, after, clock_ms):
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
    """How many of each token are on the board in this snapshot. Comparing
    two of these across snapshots reveals which pieces left the board --
    i.e. were captured -- no matter where surviving pieces moved to."""
    return Counter(f"{p.color}{p.kind}" for p in snapshot.pieces)
