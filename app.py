"""Graphical entry point for Kung-Fu Chess.

This is deliberately thin. Every piece of logic -- coordinate conversion, the
clock, click routing, sprite choice, animation -- lives in tested classes. app.py
only wires them to OpenCV: it opens a window, forwards mouse events, and redraws
each frame. Nothing here decides a game rule, so nothing here needs a test; the
one untestable part (a real window) is marked no-cover.

Run it with:  python app.py
The text protocol entry point is still main.py; this is a separate front end, so
the VPL path is untouched.
"""

import cv2

from engine.game import GameEngine
from input.board_mapper import BoardMapper
from input.controller import Controller
from input.game_clock import GameClock
from model.board import Board
from model.config import Config
from view.animation_set import AnimationSet
from view.img import Img
from view.observer import GameObserver
from view.renderer import Renderer
from view.score_panel import ScorePanel
from view.sprite_library import SpriteLibrary

_WINDOW = "Kung-Fu Chess"
_ASSETS = "assets"
_PIECES = _ASSETS + "/pieces_mine"
_BOARD_PNG = _ASSETS + "/board.png"

_START = [
    ["bR", "bN", "bB", "bQ", "bK", "bB", "bN", "bR"],
    ["bP", "bP", "bP", "bP", "bP", "bP", "bP", "bP"],
    [".", ".", ".", ".", ".", ".", ".", "."],
    [".", ".", ".", ".", ".", ".", ".", "."],
    [".", ".", ".", ".", ".", ".", ".", "."],
    [".", ".", ".", ".", ".", ".", ".", "."],
    ["wP", "wP", "wP", "wP", "wP", "wP", "wP", "wP"],
    ["wR", "wN", "wB", "wQ", "wK", "wB", "wN", "wR"],
]


def build_game(config=None):  # pragma: no cover
    """Compose the whole graphical stack and return the parts app.py drives.
    Split out so it reads top-down; still untested because it wires real assets
    and OpenCV, but it only calls classes that are themselves tested."""
    config = config or Config(cell_size=102)             # 822 / 8 ~= 102
    board = Board([row[:] for row in _START], config)
    engine = GameEngine(board, config)
    controller = Controller(engine, BoardMapper(board, config), board, config)

    board_image = Img().read(_BOARD_PNG)
    image_h, image_w = board_image.img.shape[:2]

    sprites = SpriteLibrary(_PIECES, cell_size=(config.cell_size, config.cell_size))
    animations = AnimationSet(_PIECES)
    renderer = Renderer(sprites, lambda p: Img().read(p), _BOARD_PNG,
                        animation=animations.frame)

    clock = GameClock(engine)
    observer = GameObserver(config)
    panel = ScorePanel(observer, x=image_w + 20, y=40)
    return engine, controller, renderer, clock, observer, panel


def run():  # pragma: no cover
    """Open the window and run the frame loop until the game ends or Esc/Q is
    pressed. Each frame: advance the clock, redraw the snapshot, pump events."""
    engine, controller, renderer, clock, observer, panel = build_game()

    def on_mouse(event, x, y, _flags, _param):
        # OpenCV reports x, y already in image pixels, even when the window is
        # resized (verified empirically), so the click goes straight to the
        # controller with no coordinate conversion.
        if event == cv2.EVENT_LBUTTONDOWN:
            controller.click(x, y)
        elif event == cv2.EVENT_RBUTTONDOWN:
            controller.jump(x, y)

    cv2.namedWindow(_WINDOW, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(_WINDOW, on_mouse)

    while True:
        clock.tick()
        snapshot = engine.snapshot(controller.selection)
        observer.observe(snapshot, clock.elapsed_ms())   # updates at its own pace
        frame = renderer.render(snapshot, clock.elapsed_ms())
        panel.draw(frame)
        cv2.imshow(_WINDOW, frame.img)
        key = cv2.waitKey(16) & 0xFF                      # ~60 fps
        if key in (27, ord("q")) or engine.game_over:
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    run()  # pragma: no cover
