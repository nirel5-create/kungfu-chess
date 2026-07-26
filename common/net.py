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
"""

from common import protocol


class GameSession:
    """Owns one GameEngine for a match. No asyncio, no sockets -- the server
    is the only thing that ticks it and broadcasts what it returns."""

    def __init__(self, engine):
        self._engine = engine

    def submit(self, message):
        """Apply one already-decoded command dict (already validated by
        protocol.loads) to the engine. A `move` calls request_move, a `jump`
        calls request_jump; any other type -- unknown, or a leftover from a
        message kind this session does not act on -- is ignored rather than
        raised, since the caller has already validated the wire shape and this
        is only defence in depth. Does not advance time.

        Cells arrive as JSON lists, but the engine uses them as dict/set keys
        internally (RealTimeArbiter tracks motions by cell), so each list is
        converted to a tuple here before it reaches the engine."""
        message_type = message.get("type")
        if message_type == protocol.MOVE:
            self._engine.request_move(tuple(message["src"]), tuple(message["dst"]))
        elif message_type == protocol.JUMP:
            self._engine.request_jump(tuple(message["cell"]))

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
