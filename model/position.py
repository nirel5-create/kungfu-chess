from collections import namedtuple


class Position(namedtuple("Position", "row col")):
    """A board cell. Not pixels -- pixels belong to BoardMapper and the
    renderer (guide S6).

    A value object: two positions with the same row and column are equal, and
    it prints readably so an assertion failure is legible. It does not know the
    board's size; bounds belong to Board.

    It subclasses tuple deliberately, so Position(0, 1) == (0, 1). Cells were
    plain tuples before this class existed, and every one of them keeps working.
    """

    __slots__ = ()

    def __repr__(self):
        return "Position(row={}, col={})".format(self.row, self.col)

    def offset(self, dr, dc):
        return Position(self.row + dr, self.col + dc)
