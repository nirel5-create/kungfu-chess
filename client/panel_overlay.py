"""ScorePanel's read-only view of "the observer" (view/score_panel.py,
frozen, reads log(), score_of(color) and name_of(color)) -- backed by
whatever the server's own `history` message last reported (Step 11), never
a real view.observer.GameObserver.

The server runs its own GameObserver per game (server.py's _tick_loop) and
sends the current log, scores and names whenever they change, or
immediately when a connection joins or reconnects -- so every client,
including one that joined or reconnected mid-game, shows the exact same
history from the start, computed once, server-side, rather than each
client computing its own from only what it happened to see (the bug this
step fixes: a reconnecting player used to see an empty panel).

Built the same way client.py's _SnapshotBoard wraps _ServerLink for
Controller/BoardMapper: holds a reference to whatever supplies `history()`
and reads it lazily on each call, rather than being pushed updates.
"""


class PanelOverlay:
    """ScorePanel's adapter for _ServerLink.history() -- see this module's
    own docstring."""

    def __init__(self, link):
        """link -- anything with a `history()` method returning a
        (white_name, black_name, white_score, black_score, log) object,
        or None before the server's first `history` message has arrived
        -- in practice client.py's _ServerLink, kept generic here (no
        import of it) the same way _SnapshotBoard's own `link` parameter
        is never type-checked against _ServerLink specifically."""
        self._link = link

    def log(self):
        """-> the capture log so far, oldest first -- () before the first
        `history` message arrives, matching GameObserver.log()'s own
        "nothing yet" shape (an empty tuple, not None), so ScorePanel
        needs no special case for either source."""
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
