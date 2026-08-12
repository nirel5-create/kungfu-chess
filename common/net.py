"""Splits app.py's frame loop -- clock.tick() -> engine.snapshot() ->
renderer.render() -- across a wire, without either half touching a
socket. GameSession (server half) turns a decoded protocol message into
an engine call; ClientProxy (client half) stands in for GameEngine, so
input.Controller keeps calling request_move/request_jump exactly as
before, each call now serialised to a `send` callable -- neither class
nor Controller needs to know which side of the wire it is on.

Ownership -- who may move a given piece -- is enforced here, in
GameSession.submit, not in GameEngine (which knows what is *legal*, not
who is *allowed to ask*, so checking color there would break local play,
where one person moves both sides) and not by the client (color never
travels in a `move`/`jump` message, since a client claiming "color": "b"
could move the opponent's pieces). The server knows who you are from the
connection, not from what a client claims."""

from common import protocol

ANY_COLOR = "any"   # local play: ownership is not enforced


class GameSession:
    """Owns one GameEngine for a match. No asyncio, no sockets -- the server
    is the only thing that ticks it and broadcasts what it returns."""

    def __init__(self, engine):
        self._engine = engine
        self._forced_game_over = False  # set by force_game_over(); see its docstring

    def submit(self, message, color=ANY_COLOR):
        """Apply one already-decoded command dict to the engine, after
        checking `color` owns the piece named. `color` defaults to
        ANY_COLOR so local play (one person moving both sides) keeps
        working. An unrecognised type or an ownership refusal is
        ignored, never raised. -> True if forwarded, False if refused."""
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
        """Whether `color` may act on the piece at `cell`. ANY_COLOR:
        always (local play). "viewer": never. "w"/"b": only if that
        color owns the piece there -- an empty cell has no owner, so
        this is also False."""
        if color == ANY_COLOR:
            return True
        if color == "viewer":
            return False
        return self._piece_color_at(tuple(cell)) == color

    def _piece_color_at(self, cell):
        """The color of the piece at `cell`, or None if the cell is empty.
        The engine has no "piece at cell" accessor (it is frozen), so this
        walks snapshot().pieces instead -- the same lookup client.py's
        _SnapshotBoard.piece_at does on the client side, so there is one
        approach to "what is on this cell", used consistently, not two."""
        row, col = cell
        for piece in self._engine.snapshot().pieces:
            if piece.row == row and piece.col == col:
                return piece.color
        return None

    def advance(self, ms):
        """Move the engine's simulated clock forward by exactly `ms`."""
        self._engine.wait(ms)

    def force_game_over(self):
        """Mark this session over without the engine's own capture-based
        ending -- used for disconnect auto-resign, where no king was
        captured. The (frozen) engine is never told; `game_over` and
        snapshot() reflect the forced end immediately, so the client's
        existing game-over handling fires with no separate code path."""
        self._forced_game_over = True

    def snapshot(self):
        """-> the engine's current GameSnapshot, with `game_over` forced
        True once force_game_over() has been called (the frozen engine
        is never told, so its own snapshot would not otherwise say so)."""
        snapshot = self._engine.snapshot()
        if self._forced_game_over and not snapshot.game_over:
            return snapshot._replace(game_over=True)
        return snapshot

    @property
    def game_over(self):
        """-> whether the engine has ended the game, or force_game_over()
        was called (the two can differ since a forced end never reaches
        the frozen engine)."""
        return self._engine.game_over or self._forced_game_over


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
