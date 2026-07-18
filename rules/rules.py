from model.config import TARGET_ANY, TARGET_EMPTY
from model.position import Position
from rules.results import (
    MoveValidation, VALID, REASON_OUTSIDE_BOARD, REASON_EMPTY_SOURCE,
    REASON_FRIENDLY_DESTINATION, REASON_ILLEGAL_PIECE_MOVE,
)


class RuleEngine:
    """Answers one question: given a source and a destination, is this command
    legal *right now*? Read-only with respect to the board -- it never moves a
    piece, never captures, never starts a motion, and knows nothing about time,
    turns, or game-over.

    It does not know what a 'rook' is either. It reads PieceRules as data.
    """

    def __init__(self, board, config, piece_rules=None):
        self._board = board
        self._config = config
        self._rules = piece_rules or PieceRules(board, config)

    def validate_move(self, src, dst):
        """-> MoveValidation. reason is always set; "ok" when valid."""
        if not (self._board.in_bounds(*src) and self._board.in_bounds(*dst)):
            return MoveValidation(False, REASON_OUTSIDE_BOARD)
        piece = self._board.piece_at(*src)
        if piece is None:
            return MoveValidation(False, REASON_EMPTY_SOURCE)
        dst_piece = self._board.piece_at(*dst)
        if dst_piece is not None and self._config.same_color(piece, dst_piece):
            return MoveValidation(False, REASON_FRIENDLY_DESTINATION)
        if dst not in self._rules.legal_destinations(self._board, piece, src):
            return MoveValidation(False, REASON_ILLEGAL_PIECE_MOVE)
        return VALID

    def is_legal(self, src, dst):
        """Convenience for callers that only need the boolean."""
        return self.validate_move(src, dst).is_valid


class PieceRules:
    """Strategy per piece type -- parameterised by data rather than written as
    one class per piece, so that a user-defined game (a new piece, a changed
    rule) is a Config entry and never a code change.

    Stateless: it stores no selection, no active motion, no elapsed time and no
    game-over. It only computes destinations from a board and a piece.
    """

    def __init__(self, board, config):
        self._config = config

    def legal_destinations(self, board, piece, src):
        """-> set of cells this piece may move to from `src` (guide S7).
        Enemy-occupied destinations may be included; this never captures,
        removes, moves, or mutates anything."""
        rays = self._config.rays_for(piece)
        if rays is None:
            return self._every_cell(board)  # unrestricted: no rule defined
        found = set()
        for ray in rays:
            found.update(self._ray_destinations(board, ray, piece, src))
        return found

    def _every_cell(self, board):
        return {Position(r, c) for r in range(board.rows) for c in range(board.cols)}

    def _ray_destinations(self, board, ray, piece, src):
        if ray.gated and not self._on_start_row(board, piece, src):
            return ()
        if ray.can_jump:
            cell = Position(src[0] + ray.dr, src[1] + ray.dc)
            if not board.in_bounds(*cell):
                return ()
            return (cell,) if self._target_ok(board, ray.target, cell) else ()
        return self._slide(board, ray, src)

    def _slide(self, board, ray, src):
        out = []
        step = 1
        while ray.max_steps is None or step <= ray.max_steps:
            r, c = src[0] + step * ray.dr, src[1] + step * ray.dc
            if not board.in_bounds(r, c):
                break
            if self._target_ok(board, ray.target, Position(r, c)):
                out.append(Position(r, c))
            if board.piece_at(r, c) is not None:
                break  # a slider stops at the first occupied cell
            step += 1
        return out

    def _on_start_row(self, board, piece, src):
        color = self._config.color_of(piece)
        return src[0] == self._config.start_row(color, board)

    def _target_ok(self, board, target, cell):
        occupant = board.piece_at(*cell)
        if target == TARGET_ANY:
            return True
        if target == TARGET_EMPTY:
            return occupant is None
        return occupant is not None  # TARGET_ENEMY


# Back-compat alias: the class was called MoveValidator before the guide's
# names were adopted. Kept so older call sites keep working.
MoveValidator = RuleEngine
