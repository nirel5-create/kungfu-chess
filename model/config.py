from collections import namedtuple

# --- Ray targets -------------------------------------------------------------
# What is allowed to sit on the destination cell for a ray to apply. Named so
# that neither the movement table nor the validator carries a bare string.
TARGET_ANY = "any"      # empty or enemy -- the normal case
TARGET_EMPTY = "empty"  # must be unoccupied (a pawn's forward step)
TARGET_ENEMY = "enemy"  # must hold an opponent (a pawn's diagonal capture)

# --- Ray ---------------------------------------------------------------------
# One movement option of one piece, as data. A piece's movement is just a list
# of these, so adding a piece or changing how one moves is a table edit -- no
# engine code is involved.
#
#   dr, dc     direction, in cells per step
#   max_steps  how far it may travel; None = slide until blocked or off-board
#   can_jump   True = ignore pieces in between (the knight)
#   target     what may occupy the destination; see TARGET_* above
#   gated      True = this ray only applies from the mover's own start row
#              (Config.start_row). Lets reach depend on position without the
#              engine ever branching on piece type.
#
# Defaults describe a sliding piece, so the common cases read short:
#   Ray(-1, 0)                         -> slides up, any destination
#   Ray(-1, 0, max_steps=1)            -> one step up
#   Ray(-1, 1, max_steps=1, target=TARGET_ENEMY)   -> capture only
Ray = namedtuple("Ray", "dr dc max_steps can_jump target gated")
Ray.__new__.__defaults__ = (None, False, TARGET_ANY, False)

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
        Ray(direction, 0, max_steps=1, target=TARGET_EMPTY),
        Ray(direction, 0, max_steps=2, target=TARGET_EMPTY, gated=True),
        Ray(direction, -1, max_steps=1, target=TARGET_ENEMY),
        Ray(direction, 1, max_steps=1, target=TARGET_ENEMY),
    ]


def _default_movement(orthogonal, diagonal, knight_deltas):
    all_directions = orthogonal + diagonal
    return {
        "K": [Ray(dr, dc, max_steps=1) for dr, dc in all_directions],
        "Q": [Ray(dr, dc) for dr, dc in all_directions],
        "R": [Ray(dr, dc) for dr, dc in orthogonal],
        "B": [Ray(dr, dc) for dr, dc in diagonal],
        "N": [Ray(dr, dc, max_steps=1, can_jump=True) for dr, dc in knight_deltas],
        "wP": _pawn_rules(-1),
        "bP": _pawn_rules(1),
    }


class Config:
    """All tunable rules live here. Nothing about *what* pieces exist,
    how big a cell is, or how a move settles is hardcoded in the logic.

    Config is also the only place that knows how a piece token is spelled.
    Everyone else asks (color_of / type_of / is_king / rays_for), so swapping
    the token for a different representation touches this class alone.
    """

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
        long_rest_ms=2000,
        short_rest_ms=1000,
        piece_costs=None,
        orthogonal_deltas=_ORTHOGONAL,
        diagonal_deltas=_DIAGONAL,
        knight_deltas=_KNIGHT_DELTAS,
    ):
        self.cell_size = cell_size
        self.colors = colors
        self.piece_types = piece_types
        self.empty = empty
        # movement[token or piece letter] -> list of Ray. A full token ("wP")
        # wins over the bare letter ("P"), which is how the two pawn colours
        # get opposite directions without the engine knowing what a pawn is.
        # Missing entry = unrestricted; see rays_for.
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
        # How long a piece rests after finishing a move (long) or a jump
        # (short), during which it accepts no command. Sensible defaults: the
        # real numbers live in the sprite config.json (frames / fps) but that is
        # graphics data the engine must not read, so a caller injects the exact
        # values here when the view knows them. Short < long because, per the
        # mentor, a jump is less tiring than a move.
        self.long_rest_ms = long_rest_ms
        self.short_rest_ms = short_rest_ms
        # The "cost" of each piece type, summed into a player's score when they
        # capture. Standard chess values by default; kept as data (not hardcoded
        # in the scorer) so a custom game can retune them in one place. The king
        # has no cost -- capturing it ends the game, it is never scored.
        self.piece_costs = piece_costs if piece_costs is not None else {
            "P": 1, "N": 3, "B": 3, "R": 5, "Q": 9, "K": 0,
        }

    # --- token layout: the only class that reads a token's insides ----------

    def color_of(self, token):
        return token[0]

    def type_of(self, token):
        return token[1]

    def cost_of(self, token):
        """The score value of a piece, by its type. Unknown types cost 0."""
        return self.piece_costs.get(self.type_of(token), 0)

    def is_king(self, token):
        return self.type_of(token) == self.king_type

    def is_valid_token(self, token):
        if token == self.empty:
            return True
        return (
            len(token) == 2
            and self.color_of(token) in self.colors
            and self.type_of(token) in self.piece_types
        )

    def same_color(self, token_a, token_b):
        return self.color_of(token_a) == self.color_of(token_b)

    # --- movement table lookup ---------------------------------------------

    def rays_for(self, token):
        """The movement options of this piece, or None if none are defined
        (which the validator reads as unrestricted)."""
        return self.movement.get(token, self.movement.get(self.type_of(token)))

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
        expected = self.promotion_row(self.color_of(piece), board)
        return promoted if arrival_row == expected else None
