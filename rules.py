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
        piece_type = piece[1]
        rays = self._config.movement.get(piece_type)
        if rays is None:
            return True  # unrestricted (e.g. iteration-3 pawns)
        wanted = (dst[0] - src[0], dst[1] - src[1])
        for dr, dc, max_steps, can_jump in rays:
            if can_jump:
                if wanted == (dr, dc):
                    return True
            elif self._slides_to(src, dst, dr, dc, max_steps):
                return True
        return False

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