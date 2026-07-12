class MoveValidator:
    """Interprets the movement table. Knows board geometry -- not turn state.
    Adding a new piece never touches this class: it reads rules as data."""

    def __init__(self, board, config):
        self._board = board
        self._config = config

    def is_legal(self, src, dst):
        piece = self._board.piece_at(*src)
        dst_piece = self._board.piece_at(*dst)
        if dst_piece is not None and self._config.same_color(piece, dst_piece):
            return False
        rays = self._config.movement.get(piece, self._config.movement.get(piece[1]))
        if rays is None:
            return True  # unrestricted: no rule defined for this piece type
        wanted = (dst[0] - src[0], dst[1] - src[1])
        for dr, dc, max_steps, can_jump, target, gated in rays:
            if not self._target_ok(target, dst_piece):
                continue
            if gated and src[0] != self._config.start_row(piece[0], self._board):
                continue
            if can_jump:
                if wanted == (dr, dc):
                    return True
            elif self._slides_to(src, dst, dr, dc, max_steps):
                return True
        return False

    def _target_ok(self, target, dst_piece):
        if target == "any":
            return True
        if target == "empty":
            return dst_piece is None
        return dst_piece is not None  # target == "enemy"

    def _slides_to(self, src, dst, dr, dc, max_steps):
        step = 1
        while max_steps is None or step <= max_steps:
            r, c = src[0] + step * dr, src[1] + step * dc
            if not self._board.in_bounds(r, c):
                return False
            if (r, c) == dst:
                return True
            if self._board.piece_at(r, c) is not None:
                return False
            step += 1
        return False