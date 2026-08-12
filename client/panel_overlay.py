"""A read-only adapter that presents the server's `history` message
(log, scores, names) in the shape ScorePanel (frozen, reads log(),
score_of(color) and name_of(color)) expects.

The server computes one authoritative history per game and sends it
whenever it changes, so every client -- including one that reconnects
mid-game -- shows the identical history from the start, rather than each
client computing its own from only what it happened to see.

Holds a reference to whatever supplies `history()` and reads it lazily
on each call, rather than being pushed updates.
"""


class PanelOverlay:
    """Adapts a `history()`-providing link to ScorePanel's read interface."""

    def __init__(self, link):
        """link -- anything with a `history()` method returning a
        (white_name, black_name, white_score, black_score, log) object,
        or None before the server's first `history` message has arrived."""
        self._link = link

    def log(self):
        """-> the capture log so far, oldest first -- () before the
        first `history` message arrives, matching GameObserver.log()'s
        "nothing yet" shape so ScorePanel needs no special case."""
        history = self._link.history()
        return () if history is None else history.log

    def score_of(self, color):
        """-> `color`'s running score, or 0 before the first `history`
        message arrives -- matches GameObserver.score_of's own starting
        value."""
        history = self._link.history()
        if history is None:
            return 0
        return history.white_score if color == "w" else history.black_score

    def name_of(self, color):
        """-> `color`'s current display name, or the same "Player 1"/
        "Player 2" placeholder GameObserver itself defaults to, before
        the first `history` message arrives."""
        history = self._link.history()
        if history is None:
            return "Player 1" if color == "w" else "Player 2"
        return history.white_name if color == "w" else history.black_name
