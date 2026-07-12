# Default direction vectors for the standard chess movement patterns --
# overridable via Config(orthogonal_deltas=..., diagonal_deltas=...,
# knight_deltas=...) for custom piece geometry, no engine change needed.
_ORTHOGONAL = ((-1, 0), (1, 0), (0, -1), (0, 1))
_DIAGONAL = ((-1, -1), (-1, 1), (1, -1), (1, 1))
_KNIGHT_DELTAS = (
    (-2, -1), (-2, 1), (-1, -2), (-1, 2),
    (1, -2), (1, 2), (2, -1), (2, 1),
)


def _pawn_rules(direction):
    # direction: -1 = up the board (white), +1 = down the board (black).
    return [
        (direction, 0, 1, False, "empty", False),   # forward one, always
        (direction, 0, 2, False, "empty", True),    # forward two, only from start row
        (direction, -1, 1, False, "enemy", False),  # capture diagonally
        (direction, 1, 1, False, "enemy", False),
    ]


def _default_movement(orthogonal, diagonal, knight_deltas):
    # Ray tuple: (dr, dc, max_steps, can_jump, target, gated).
    # max_steps=None means "slide until blocked or off-board".
    # target: "any" (empty or enemy ok), "empty" (must be unoccupied),
    # or "enemy" (must hold an opposing piece) -- lets move geometry
    # and capture geometry differ (needed for pawns).
    # gated: False means always available; True means the ray only
    # applies when the mover sits on ITS OWN start row
    # (Config.start_row) -- lets reach depend on position with no
    # branching on piece type anywhere in the engine.
    all_directions = orthogonal + diagonal
    return {
        "K": [(dr, dc, 1, False, "any", False) for dr, dc in all_directions],
        "Q": [(dr, dc, None, False, "any", False) for dr, dc in all_directions],
        "R": [(dr, dc, None, False, "any", False) for dr, dc in orthogonal],
        "B": [(dr, dc, None, False, "any", False) for dr, dc in diagonal],
        "N": [(dr, dc, 1, True, "any", False) for dr, dc in knight_deltas],
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
        jump_ms=1000,
        orthogonal_deltas=_ORTHOGONAL,
        diagonal_deltas=_DIAGONAL,
        knight_deltas=_KNIGHT_DELTAS,
    ):
        self.cell_size = cell_size
        self.colors = colors
        self.piece_types = piece_types
        self.empty = empty
        # movement[piece_letter] -> ray tuples; see _default_movement() for the
        # exact shape. Missing entry = unrestricted (any dst legal).
        self.movement = (
            _default_movement(orthogonal_deltas, diagonal_deltas, knight_deltas)
            if movement is None
            else movement
        )
        # ms to cross one cell; N cells = N * piece_speed_ms.
        self.piece_speed_ms = piece_speed_ms
        # Which piece type ends the game when captured.
        self.king_type = king_type
        # promotions[piece_token] -> token it becomes on arrival at the
        # opposite color's start row. Data, not an engine special case --
        # a custom game can remap this freely.
        self.promotions = {"wP": "wQ", "bP": "bQ"} if promotions is None else promotions
        # ms a piece stays airborne after `jump`.
        self.jump_ms = jump_ms

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

    def _is_first_color(self, color):
        # ASSUMES exactly two configured colors (self.colors) -- the only
        # case this project needs. A 3+ color variant would need a
        # different resolution rule here; not supported.
        return color == self.colors[0]

    def start_row(self, color, board):
        # Pawn double-step origin -- the second rank, one square in from
        # the edge that color enters from. White (colors[0]) enters at
        # the bottom edge, so it starts one row above it; black mirrors
        # this from the top edge.
        return board.rows - 2 if self._is_first_color(color) else 1

    def promotion_row(self, color, board):
        # The far edge color's pawns are walking toward -- always the
        # extreme row, independent of where start_row sits.
        return 0 if self._is_first_color(color) else board.rows - 1

    def promotion_target(self, piece, arrival_row, board):
        promoted = self.promotions.get(piece)
        if promoted is None:
            return None
        return promoted if arrival_row == self.promotion_row(piece[0], board) else None