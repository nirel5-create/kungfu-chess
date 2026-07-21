"""Draws a GameSnapshot: the board, then every piece on it.

The renderer receives a GameSnapshot and nothing else -- never a live Board or
Piece (guide S19). Everything it needs (each piece's token, pixel position and
lifecycle state) is already on the snapshot, so it cannot touch game state.

The state->sprite-folder mapping lives here because it is a drawing concern:
the engine's `moving` is the sprites' `move`, its `jumping` is `jump`. The
engine does not know these folder names exist.
"""

import math

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
        self._board_template = None   # the board is loaded once and cloned per
        #                               frame; reading the png every frame was the
        #                               main cost that made motion stutter.

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
        drawing: cell (row, col) maps to a cell_size square at
        (offset_x + col*size, offset_y + row*size), the same offset the pieces
        use, so the glow lands on the piece and not beside it."""
        cell = snapshot.selected_cell
        if cell is None:
            return None
        row, col = cell
        size = snapshot.cell_size
        off_x, off_y = snapshot.board_offset
        return off_x + col * size, off_y + row * size, size, size

    def render(self, snapshot, clock_ms=0):
        """Draw the board, the selection highlight, each piece, and a small
        overlay marking its state (a jumping piece gets a halo; a resting one is
        dimmed with a filling timer ring). The one method that actually paints,
        so it is the only part that needs the image library at runtime."""
        board = self._fresh_board()
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
            lift = _jump_lift(piece.state, clock_ms, snapshot.cell_size)
            drift = _breathe_offset(piece.state, clock_ms, snapshot.cell_size)
            sway = _walk_sway(piece.state, clock_ms, snapshot.cell_size)
            frame.draw_on(board, x + round(sway), y - round(lift + drift))
        return board

    def _fresh_board(self):
        """A clean board image to paint this frame's pieces onto. The board png
        is read from disk only the first time; after that each frame clones the
        cached pixels, which is far cheaper than decoding the file every frame
        and is what keeps the animation smooth at 60fps."""
        if self._board_template is None:
            self._board_template = self._load_board(self._board_path)
        template = self._board_template
        clone = type(template)()
        clone.img = template.img.copy()
        return clone

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


_SELECT_GLOW = (255, 240, 200)   # cool silver-white glow for the selected piece, BGR
_SELECT_ALPHA = 0.30
_JUMP_GLOW = (255, 220, 150)     # bright crystal-blue halo for a jumping piece
_JUMP_ALPHA = 0.40
_REST_DIM = (90, 70, 50)         # cool slate wash for a resting piece
_REST_ALPHA = 0.35
_RING_DOT_ON = (225, 105, 65)    # crystal blue, BGR -- reads on light and dark
_RING_DOT_OFF = (140, 110, 90)   # faint slate for not-yet-elapsed dots

# Motion is drawn, not stored: an idle piece breathes (a gentle vertical float),
# a walking piece sways, and an airborne piece hops. All come from the clock, so
# the same still sprite animates without extra frames -- fitting for gliding
# crystal pieces.
_BREATHE_PERIOD_MS = 2200        # one gentle float up and back, lively but calm
_BREATHE_FLOAT = 0.03            # idle pieces drift +-3% of a cell vertically
_JUMP_HEIGHT = 0.15              # peak hop is 15% of a cell, clearly readable
_JUMP_PERIOD_MS = 900            # one calm up-and-down hop while airborne
_WALK_PERIOD_MS = 600            # one side-to-side lilt while walking
_WALK_SWAY = 0.025               # +-2.5% of a cell, a subtle walking gait


def _breathe_offset(state, clock_ms, cell_size):
    """Vertical drift for an idle piece this frame: a slow, smooth float up and
    back rather than a size change, which at cell resolution would jump between
    whole pixels and stutter. Zero for any non-idle piece. Returns a float so
    the caller rounds once, together with any jump lift."""
    if state != STATE_IDLE:
        return 0.0
    phase = math.sin(2 * math.pi * (clock_ms % _BREATHE_PERIOD_MS)
                     / _BREATHE_PERIOD_MS)
    return _BREATHE_FLOAT * cell_size * phase


def _walk_sway(state, clock_ms, cell_size):
    """Horizontal sway for a moving piece this frame: a small side-to-side lilt
    on a quick cycle, so a gliding piece reads as walking rather than sliding
    stiffly. Zero for any piece that is not moving. Returns a float for the
    caller to round."""
    if state != STATE_MOVING:
        return 0.0
    phase = math.sin(2 * math.pi * (clock_ms % _WALK_PERIOD_MS) / _WALK_PERIOD_MS)
    return _WALK_SWAY * cell_size * phase


def _jump_lift(state, clock_ms, cell_size):
    """How many pixels to raise an airborne piece this frame. The piece rises
    and falls once per cycle following a single smooth arc (sin over half a
    period), so it reads as one clean hop, not a stutter. Returns a float for
    sub-pixel smoothness; the caller rounds once. Zero when not jumping."""
    if state != STATE_JUMPING:
        return 0.0
    arc = math.sin(math.pi * (clock_ms % _JUMP_PERIOD_MS) / _JUMP_PERIOD_MS)
    return _JUMP_HEIGHT * cell_size * arc


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
    """Draw a ring of twelve dots around a cell that light up clockwise as the
    cooldown elapses (progress 0 -> 1), like a clock face. Lit dots are a
    crystal blue with a soft glow -- mid-toned so they read on both light and
    dark squares -- and unlit dots are faint. Rendered on a 4x supersampled
    overlay for crisp, jewel-like dots, then blended down. Zero draws nothing."""
    if progress <= 0:
        return
    import cv2  # noqa: C0415 -- only the real draw path needs OpenCV; tests inject fakes
    import numpy as np

    scale = 4                                   # supersample for smooth dots
    big = size * scale
    overlay = np.zeros((big, big, 3), dtype=np.uint8)
    mask = np.zeros((big, big), dtype=np.float32)
    centre = big // 2
    radius = big // 2 - 6 * scale               # dot ring sits inside the cell
    count = 12
    lit = round(count * min(1.0, progress))
    for i in range(count):
        angle = -math.pi / 2 + 2 * math.pi * i / count
        cx = int(centre + radius * math.cos(angle))
        cy = int(centre + radius * math.sin(angle))
        on = i < lit
        colour = _RING_DOT_ON if on else _RING_DOT_OFF
        dot_r = 4 * scale if on else 2 * scale
        if on:                                  # soft glow behind a lit dot
            cv2.circle(overlay, (cx, cy), dot_r * 2, colour, -1, cv2.LINE_AA)
            cv2.circle(mask, (cx, cy), dot_r * 2, 0.35, -1, cv2.LINE_AA)
        cv2.circle(overlay, (cx, cy), dot_r, colour, -1, cv2.LINE_AA)
        cv2.circle(mask, (cx, cy), dot_r, 1.0 if on else 0.4, -1, cv2.LINE_AA)

    small = cv2.resize(overlay, (size, size), interpolation=cv2.INTER_AREA)
    small_mask = cv2.resize(mask, (size, size), interpolation=cv2.INTER_AREA)

    h, w = board_img.img.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(w, x + size), min(h, y + size)
    if x0 >= x1 or y0 >= y1:
        return
    region = board_img.img[y0:y1, x0:x1]
    a = small_mask[y0 - y:y1 - y, x0 - x:x1 - x][..., None]
    band = small[y0 - y:y1 - y, x0 - x:x1 - x]
    rgb = region[..., :3]                        # ignore alpha on RGBA boards
    rgb[:] = (rgb * (1 - a) + band * a).astype(rgb.dtype)
