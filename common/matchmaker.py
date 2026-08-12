"""Pure matchmaking queue for Play: who is waiting, at what rating, for
how long, and which two of them should be paired.

No sockets, no database, no wall clock -- time is explicit, passed into
advance(ms), the same discipline common.net.GameSession.advance(ms) and
common.registry.GameRegistry.advance(ms) already keep. That is what makes
the one-minute timeout rule testable without waiting a minute.

What this module owns: the queue itself, and the pairing/timeout policy.
What it does NOT own: creating games (GameRegistry.create), reading a
player's rating from the database (common.db.get_rating), or sending any
message -- server.py is the one place that knows about all three and wires
them to this queue's return values.
"""

RATING_WINDOW = 100        # an opponent within +-100 rating
SEARCH_TIMEOUT_MS = 60000  # give up after one minute


class MatchMaker:
    """A queue of seekers, paired by nearest rating within `window`, aged
    out after `timeout_ms` of waiting. Call advance(ms) once per tick --
    exactly the shape GameRegistry.advance already has."""

    def __init__(self, window=RATING_WINDOW, timeout_ms=SEARCH_TIMEOUT_MS):
        self._window = window
        self._timeout_ms = timeout_ms
        self._waiting = {}  # username -> (rating, ms_waited)

    def enqueue(self, username, rating):
        """Add `username` to the queue at `rating`, wait counter at 0. A
        username already waiting is left exactly as it was -- a no-op,
        not an error, since a client can retry its own play() (e.g. after
        a dropped ack); resetting their wait counter on a retry would let
        a repeatedly-retried search never time out."""
        if username in self._waiting:
            return
        self._waiting[username] = (rating, 0)

    def cancel(self, username):
        """Remove `username` from the queue, if present. A no-op for a
        username not waiting -- the caller (server.py) cancels
        unconditionally on disconnect, whether or not this player was
        ever actually queued."""
        self._waiting.pop(username, None)

    def waiting(self):
        """-> a tuple of usernames currently queued, for logging only."""
        return tuple(self._waiting)

    def advance(self, ms):
        """Age every seeker by `ms`, pair whoever can be paired, then
        report whoever has now waited past `timeout_ms`. -> (pairs,
        timed_out); every returned username leaves the queue. Pairing
        runs BEFORE the timeout check, so a seeker crossing the deadline
        who could also be paired this call is paired, not timed out."""
        self._waiting = {username: (rating, waited + ms)
                          for username, (rating, waited) in self._waiting.items()}

        pairs = self._pair_all()
        for user_a, user_b in pairs:
            del self._waiting[user_a]
            del self._waiting[user_b]

        timed_out = [username for username, (_rating, waited) in self._waiting.items()
                     if waited >= self._timeout_ms]
        for username in timed_out:
            del self._waiting[username]

        return pairs, timed_out

    def _pair_all(self):
        """-> every pairing possible this call, closest-rating-first:
        pairing arbitrarily could match two seekers 90 points apart while
        leaving a pair 5 points apart unmatched. Sorting by rating first
        keeps the closest remaining pair always adjacent, so each round
        only scans neighbours, removes the pair just made, and repeats."""
        remaining = sorted(self._waiting.items(), key=lambda item: item[1][0])
        pairs = []
        while True:
            best_index = None
            best_diff = None
            for i in range(len(remaining) - 1):
                diff = abs(remaining[i][1][0] - remaining[i + 1][1][0])
                if diff <= self._window and (best_diff is None or diff < best_diff):
                    best_diff = diff
                    best_index = i
            if best_index is None:
                break
            (user_a, _), (user_b, _) = remaining[best_index], remaining[best_index + 1]
            pairs.append((user_a, user_b))
            del remaining[best_index:best_index + 2]
        return pairs
