"""Draws a GameSnapshot: the board, then every piece on it.

The renderer receives a GameSnapshot and nothing else -- never a live Board or
Piece (guide S19). Everything it needs (each piece's token, pixel position and
lifecycle state) is already on the snapshot, so it cannot touch game state.

The state->sprite-folder mapping lives here because it is a drawing concern:
the engine's `moving` is the sprites' `move`, its `jumping` is `jump`. The
engine does not know these folder names exist.
"""

from model.snapshot import (
    STATE_IDLE, STATE_MOVING, STATE_JUMPING, STATE_RESTING_LONG, STATE_RESTING_SHORT,
)

# engine lifecycle state -> sprite state folder. The engine now reports long and
# short rest separately, so each maps to its own sprite folder -- a piece
# recovering from a move looks different from one recovering from a jump.
_STATE_TO_FOLDER = {
    STATE_IDLE: "idle",
    STATE_MOVING: "move",
    STATE_JUMPING: "jump",
    STATE_RESTING_LONG: "long_rest",
    STATE_RESTING_SHORT: "short_rest",
}


class Renderer:
    def __init__(self, sprites, board_image_loader, board_path, animation=None):
        """sprites -- a SpriteLibrary.
        board_image_loader -- callable(path) -> a fresh board image each frame.
            Fresh, because draw_on paints onto the image in place; reusing one
            would stack every past frame's pieces on it.
        board_path -- path to the board png.
        animation -- callable(frames, state, clock_ms) -> one frame to draw, or
            None to always draw the first frame. Injected so wave 1 can draw a
            static board and wave 2 can add animation without touching this class.
        """
        self._sprites = sprites
        self._load_board = board_image_loader
        self._board_path = board_path
        self._pick_frame = animation if animation is not None else _first_frame

    def sprite_state(self, piece_state):
        """The sprite folder a piece in this lifecycle state is drawn from."""
        return _STATE_TO_FOLDER.get(piece_state, "idle")

    def token_of(self, piece):
        """The board token for a piece view: colour then type, e.g. wR."""
        return f"{piece.color}{piece.kind}"

    def placements(self, snapshot, clock_ms=0):
        """Where each piece should be drawn, as (frame, x, y) tuples. Pure: no
        drawing happens, so the layout can be asserted in a test without a
        window. A piece whose sprites are missing is skipped rather than crashing
        the whole frame."""
        out = []
        for piece in snapshot.pieces:
            token = self.token_of(piece)
            state = self.sprite_state(piece.state)
            frames = self._sprites.frames(token, state)
            if not frames:
                continue
            frame = self._pick_frame(frames, token, state, clock_ms)
            out.append((frame, int(piece.x), int(piece.y)))
        return out

    def highlight_rect(self, snapshot):
        """The pixel rectangle (x, y, w, h) to tint for the selected cell, or
        None if nothing is selected. Pure geometry, so it is testable without
        drawing: cell (row, col) maps to a cell_size square at (col*size,
        row*size)."""
        cell = snapshot.selected_cell
        if cell is None:
            return None
        row, col = cell
        size = snapshot.cell_size
        return col * size, row * size, size, size

    def render(self, snapshot, clock_ms=0):
        """Draw the board, the selection highlight, each piece, and a small
        overlay marking its state (a jumping piece gets a halo; a resting one is
        dimmed with a filling timer ring). The one method that actually paints,
        so it is the only part that needs the image library at runtime."""
        board = self._load_board(self._board_path)
        rect = self.highlight_rect(snapshot)
        if rect is not None:
            _tint(board, rect, _SELECT_GLOW, _SELECT_ALPHA)
        for piece in snapshot.pieces:
            token = self.token_of(piece)
            state = self.sprite_state(piece.state)
            frames = self._sprites.frames(token, state)
            if not frames:
                continue
            x, y = int(piece.x), int(piece.y)
            self._draw_state_overlay(board, piece, x, y, snapshot.cell_size)
            frame = self._pick_frame(frames, token, state, clock_ms)
            frame.draw_on(board, x, y)
        return board

    def _draw_state_overlay(self, board, piece, x, y, size):
        """Paint the marker for a piece's state under the sprite: a coloured
        halo behind a jumper, a dim wash plus a filling ring behind a rester.
        Idle and moving pieces get nothing."""
        cell_rect = (x, y, size, size)
        if piece.state == STATE_JUMPING:
            _tint(board, cell_rect, _JUMP_GLOW, _JUMP_ALPHA)
        elif piece.state in (STATE_RESTING_LONG, STATE_RESTING_SHORT):
            _tint(board, cell_rect, _REST_DIM, _REST_ALPHA)
            _draw_ring(board, x, y, size, piece.rest_progress)


def _first_frame(frames, token, state, clock_ms):  # noqa: ARG001 -- interface match
    """Default frame picker: the first sprite. Takes the same arguments as
    AnimationSet.frame (token, state, clock_ms) so the two are interchangeable,
    even though a still board needs none of them."""
    return frames[0]


_SELECT_GLOW = (120, 220, 255)   # warm select highlight, BGR
_SELECT_ALPHA = 0.35
_JUMP_GLOW = (80, 200, 120)      # green halo for a jumping piece
_JUMP_ALPHA = 0.45
_REST_DIM = (40, 40, 40)         # dark wash for a resting piece -- looks "tired"
_REST_ALPHA = 0.4
_RING_COLOR = (60, 230, 255)     # the filling cooldown ring


def _tint(board_img, rect, color, alpha):
    """Blend a translucent colour over one cell of the board image, in place.
    Kept out of the mentor's Img class: it works on the numpy buffer directly,
    the same way draw_on does, so no external code is touched. Clamped to the
    image bounds so a highlight near the edge never runs off the buffer."""
    x, y, w, h = rect
    buffer = board_img.img
    height, width = buffer.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x0 >= x1 or y0 >= y1:
        return
    region = buffer[y0:y1, x0:x1]
    for channel in range(3):
        region[..., channel] = (
            (1 - alpha) * region[..., channel] + alpha * color[channel]
        )


def _draw_ring(board_img, x, y, size, progress):
    """Draw an arc around a cell that fills clockwise as the cooldown elapses
    (progress 0 -> 1). Uses cv2.ellipse on the numpy buffer directly. A progress
    of zero draws nothing, so a piece that just started resting is not ringed."""
    if progress <= 0:
        return
    import cv2  # noqa: C0415 -- only the real draw path needs OpenCV; tests inject fakes

    centre = (x + size // 2, y + size // 2)
    radius = size // 2 - 4
    end_angle = -90 + int(360 * min(1.0, progress))
    cv2.ellipse(board_img.img, centre, (radius, radius), 0, -90, end_angle,
                _RING_COLOR, thickness=4, lineType=cv2.LINE_AA)
