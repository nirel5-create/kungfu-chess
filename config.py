# Direction vectors used to build the standard chess movement patterns.
_ORTHOGONAL = ((-1, 0), (1, 0), (0, -1), (0, 1))
_DIAGONAL = ((-1, -1), (-1, 1), (1, -1), (1, 1))
_ALL_DIRECTIONS = _ORTHOGONAL + _DIAGONAL
_KNIGHT_DELTAS = (
    (-2, -1), (-2, 1), (-1, -2), (-1, 2),
    (1, -2), (1, 2), (2, -1), (2, 1),
)


def _pawn_rules(direction):
    # direction: -1 = up the board (white), +1 = down the board (black).
    return [
        (direction, 0, 1, False, "empty", None),       # forward one, always
        (direction, 0, 2, False, "empty", direction),  # forward two, only from start row
        (direction, -1, 1, False, "enemy", None),      # capture diagonally
        (direction, 1, 1, False, "enemy", None),
    ]


def _default_movement():
    # Ray tuple: (dr, dc, max_steps, can_jump, target, from_row).
    # max_steps=None means "slide until blocked or off-board".
    # target: "any" (empty or enemy ok), "empty" (must be unoccupied),
    # or "enemy" (must hold an opposing piece) -- lets move geometry
    # and capture geometry differ (needed for pawns).
    # from_row: None means always available; any other value means the
    # ray only applies when the mover sits on ITS OWN start row
    # (Config.pawn_start_row) -- lets reach depend on position with no
    # branching on piece type anywhere in the engine.
    return {
        "K": [(dr, dc, 1, False, "any", None) for dr, dc in _ALL_DIRECTIONS],
        "Q": [(dr, dc, None, False, "any", None) for dr, dc in _ALL_DIRECTIONS],
        "R": [(dr, dc, None, False, "any", None) for dr, dc in _ORTHOGONAL],
        "B": [(dr, dc, None, False, "any", None) for dr, dc in _DIAGONAL],
        "N": [(dr, dc, 1, True, "any", None) for dr, dc in _KNIGHT_DELTAS],
        "wP": _pawn_rules(-1),
        "bP": _pawn_rules(1),
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
        piece_speed_ms=1000,
        king_type="K",
        promotions=None,
    ):
        self.cell_size = cell_size
        self.colors = colors
        self.piece_types = piece_types
        self.empty = empty
        # movement[piece_letter] -> list of ray tuples (dr, dc, max_steps, can_jump).
        # Missing entry = unrestricted (any dst legal).
        self.movement = _default_movement() if movement is None else movement
        # ms to cross one cell; N cells = N * piece_speed_ms (iteration 5).
        self.piece_speed_ms = piece_speed_ms
        # Which piece type ends the game when captured (iteration 8).
        self.king_type = king_type
        # promotions[piece_token] -> token it becomes on arrival at the
        # opposite color's start row (iteration 9). Data, not an engine
        # special case -- a custom game can remap this freely.
        self.promotions = {"wP": "wQ", "bP": "bQ"} if promotions is None else promotions

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
        # Cell-step count (Chebyshev distance), not Euclidean: a diagonal
        # step costs the same as an orthogonal one.
        steps = max(abs(dst[0] - src[0]), abs(dst[1] - src[1]))
        return steps * self.piece_speed_ms

    def pawn_start_row(self, color, board):
        # White (colors[0]) starts at the bottom edge; black at the top.
        return board.rows - 1 if color == self.colors[0] else 0

    def promotion_target(self, piece, arrival_row, board):
        promoted = self.promotions.get(piece)
        if promoted is None:
            return None
        # A pawn promotes on arrival at the row where the OPPOSITE color
        # starts -- reuses pawn_start_row, no separate row math needed.
        color = piece[0]
        opposite = self.colors[1] if color == self.colors[0] else self.colors[0]
        return promoted if arrival_row == self.pawn_start_row(opposite, board) else None