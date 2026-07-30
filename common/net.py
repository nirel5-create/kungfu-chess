"""Splits app.py's frame loop -- clock.tick() -> engine.snapshot() ->
renderer.render() -- across a wire, without either half touching a socket.

GameSession is the server half: it owns one GameEngine for a match and turns
a decoded protocol message into an engine call. ClientProxy is the client
half: it stands in for GameEngine so input.Controller can keep calling
request_move/request_jump exactly as it does against the real engine, except
each call is serialised and handed to a `send` callable instead of touching a
board. Controller depends only on that command surface, so neither class nor
Controller itself needs to know which side of the wire it is on.

What this module owns: turning a message into an engine call, and turning an
engine call into a message. What it does NOT own: sockets, asyncio, JSON
framing (that is protocol.dumps/loads), or game rules.

GameClock (input/game_clock.py) only reads the real wall clock -- tick() takes
no `ms` argument, it measures time.monotonic() itself. That makes it unusable
here: GameSession.advance(ms) must move the engine by a caller-chosen amount so
tests (and the server's fixed ~30 ms tick) get deterministic, explicit time.
So GameSession calls engine.wait(ms) directly and never holds a GameClock.

Ownership -- who is allowed to move a given piece -- is enforced here, in
GameSession.submit, not in GameEngine and not on the client. It is not a
chess rule: the engine knows what is *legal*, not who is *allowed to ask*,
so checking color there would break app.py, where local play depends on one
person moving both sides. It is also not something a client may assert:
color never travels inside a `move`/`jump` message, because a client that
could put "color": "b" in a request could move the opponent's pieces. The
server knows who you are from the connection (server.py assigns a color when
a websocket connects), not from what a client claims -- the same principle
as Server_Design.md: the client does not decide the rules, and neither does
the gateway. So responsibility splits: server.py knows WHO you are
(connection -> color), GameSession enforces the rule (does this piece belong
to that color?), and GameEngine decides legality, unchanged and frozen.
"""

from common import protocol

ANY_COLOR = "any"   # local play: ownership is not enforced


class GameSession:
    """Owns one GameEngine for a match. No asyncio, no sockets -- the server
    is the only thing that ticks it and broadcasts what it returns."""

    def __init__(self, engine):
        self._engine = engine

    def submit(self, message, color=ANY_COLOR):
        """Apply one already-decoded command dict (already validated by
        protocol.loads) to the engine, after checking that `color` owns the
        piece the message names. A `move` calls request_move, a `jump` calls
        request_jump; any other type -- unknown, or a leftover from a message
        kind this session does not act on -- is ignored rather than raised,
        since the caller has already validated the wire shape and this is
        only defence in depth. Does not advance time.

        `color` defaults to ANY_COLOR for two deliberate reasons:
        1. Local play (app.py, and any single-process use) is a supported
           mode where one person moves both sides, so "no owner" must be
           expressible.
        2. The existing tests in tests/unit/test_session.py call
           submit(message) with a single argument; the default keeps them
           passing untouched, per IRON RULE 1.

        See _may_act for the four possible values of `color` and what each
        is allowed to do. A refused command is silently dropped, never
        raised -- the same treatment as an unknown message type above.

        Cells arrive as JSON lists, but the engine uses them as dict/set keys
        internally (RealTimeArbiter tracks motions by cell), so each list is
        converted to a tuple here before it reaches the engine.

        -> True if the command was forwarded to the engine, False if it was
        refused (unrecognized type, or `color` may not act on this piece).
        This is "applied" only in the ownership sense -- the engine itself
        is still free to silently ignore an illegal move, which this class
        has no way to observe either (request_move/request_jump return
        nothing). Existing callers that ignore the return value (every
        test in tests/unit/test_session.py, and ClientProxy, which never
        calls submit at all) are unaffected -- they never looked at the
        old implicit None."""
        message_type = message.get("type")
        if message_type == protocol.MOVE:
            if self._may_act(color, message["src"]):
                self._engine.request_move(tuple(message["src"]), tuple(message["dst"]))
                return True
            return False
        if message_type == protocol.JUMP:
            if self._may_act(color, message["cell"]):
                self._engine.request_jump(tuple(message["cell"]))
                return True
            return False
        return False

    def _may_act(self, color, cell):
        """Whether `color` may act on the piece sitting at `cell` (a JSON
        list; _piece_color_at wants a tuple, matching how the engine itself
        keys motions by cell).

        - ANY_COLOR: always -- local play, ownership is not enforced.
        - "viewer": never -- a viewer may watch but not move anything.
        - "w" / "b": only if that color owns the piece at `cell`. An empty
          cell has no owner, so this is also False -- there is nothing to
          move, and the engine would have refused it anyway."""
        if color == ANY_COLOR:
            return True
        if color == "viewer":
            return False
        return self._piece_color_at(tuple(cell)) == color

    def _piece_color_at(self, cell):
        """The color of the piece at `cell`, or None if the cell is empty.
        The engine has no "piece at cell" accessor (it is frozen), so this
        walks snapshot().pieces instead -- the same lookup client.py's
        _SnapshotBoard.piece_at does against a snapshot on the client side:
        one approach to "what is on this cell", used consistently rather
        than two."""
        row, col = cell
        for piece in self._engine.snapshot().pieces:
            if piece.row == row and piece.col == col:
                return piece.color
        return None

    def advance(self, ms):
        """Move the engine's simulated clock forward by exactly `ms`."""
        self._engine.wait(ms)

    def snapshot(self):
        """-> the engine's current GameSnapshot."""
        return self._engine.snapshot()

    @property
    def game_over(self):
        """-> whether the engine has ended the game."""
        return self._engine.game_over


class ClientProxy:
    """The fake "engine" the client's Controller talks to. It never touches a
    board: every command is serialised with `protocol` and handed to `send`,
    which the real client wires to a websocket and a test wires to a list."""

    def __init__(self, send):
        """send -- a callable taking one already-built message dict."""
        self._send = send

    def request_move(self, src, dst):
        """Serialise as a `move` message and hand it to `send`."""
        self._send(protocol.move(src, dst))

    def request_jump(self, cell):
        """Serialise as a `jump` message and hand it to `send`."""
        self._send(protocol.jump(cell))
