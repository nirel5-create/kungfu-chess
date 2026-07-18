from model.position import Position

# Piece lifecycle (guide S6). A flag only: it stores no path, no destination,
# no elapsed time, no speed and no arrival logic -- those belong to Motion and
# RealTimeArbiter.
STATE_IDLE = "idle"
STATE_MOVING = "moving"
STATE_CAPTURED = "captured"


class Piece:
    """A chess piece: a stable identity plus what it is and where it is.

    Board stores tokens ("wR") because that is the format the text protocol and
    the binary representation both speak. Piece is the object view of one:
    build it with `Piece.of(token, cell, config)` when you need identity rather
    than a string.

    A piece never knows about the renderer, mouse clicks, pixels, or the text
    test syntax (guide S6).
    """

    __slots__ = ("id", "color", "kind", "cell", "state")

    def __init__(self, id, color, kind, cell, state=STATE_IDLE):
        self.id = id
        self.color = color
        self.kind = kind
        self.cell = Position(*cell)
        self.state = state

    @classmethod
    def of(cls, token, cell, config, id=None, state=STATE_IDLE):
        """Build a Piece from the board's token. Config owns the token layout,
        so this is the one bridge between the two views -- and the only thing
        that would change if the token format did."""
        cell = Position(*cell)
        return cls(
            id=id if id is not None else "{}@{},{}".format(token, cell.row, cell.col),
            color=config.color_of(token),
            kind=config.type_of(token),
            cell=cell,
            state=state,
        )

    @property
    def token(self):
        """The board's spelling of this piece."""
        return self.color + self.kind

    def __eq__(self, other):
        return isinstance(other, Piece) and self.id == other.id

    def __hash__(self):
        return hash(self.id)

    def __repr__(self):
        return "Piece(id={!r}, color={!r}, kind={!r}, cell={!r}, state={!r})".format(
            self.id, self.color, self.kind, self.cell, self.state)
