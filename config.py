# Direction vectors used to build the standard chess movement patterns.
_ORTHOGONAL = ((-1, 0), (1, 0), (0, -1), (0, 1))
_DIAGONAL = ((-1, -1), (-1, 1), (1, -1), (1, 1))
_ALL_DIRECTIONS = _ORTHOGONAL + _DIAGONAL
_KNIGHT_DELTAS = (
    (-2, -1), (-2, 1), (-1, -2), (-1, 2),
    (1, -2), (1, 2), (2, -1), (2, 1),
)


def _default_movement():
    # Ray tuple: (dr, dc, max_steps, can_jump).
    # max_steps=None means "slide until blocked or off-board".
    return {
        "K": [(dr, dc, 1, False) for dr, dc in _ALL_DIRECTIONS],
        "Q": [(dr, dc, None, False) for dr, dc in _ALL_DIRECTIONS],
        "R": [(dr, dc, None, False) for dr, dc in _ORTHOGONAL],
        "B": [(dr, dc, None, False) for dr, dc in _DIAGONAL],
        "N": [(dr, dc, 1, True) for dr, dc in _KNIGHT_DELTAS],
    }


class Config:
    """All tunable rules live here. Nothing about *what* pieces exist,
    how big a cell is, or how a move settles is hardcoded in the logic."""

    def __init__(
        self,
        cell_size=100,
        colors=("w", "b"),
        piece_types=("K", "Q", "R", "B", "N", "P"),
        empty=".",
        movement=None,
    ):
        self.cell_size = cell_size
        self.colors = colors
        self.piece_types = piece_types
        self.empty = empty
        # movement[piece_letter] -> list of ray tuples (dr, dc, max_steps, can_jump).
        # Missing entry = unrestricted (any dst legal); used for iteration 3 pawns.
        self.movement = _default_movement() if movement is None else movement

    def is_valid_token(self, token):
        if token == self.empty:
            return True
        return (
            len(token) == 2
            and token[0] in self.colors
            and token[1] in self.piece_types
        )

    def same_color(self, token_a, token_b):
        return token_a[0] == token_b[0]

    def travel_time(self, src, dst):
        # Iteration 2: no numbers are given, so moves are instant.
        # When travel time arrives, return the duration here and the
        # settle machinery in Game already handles the rest.
        return 0