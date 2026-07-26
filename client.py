"""OpenCV client for Kung-Fu Chess, driven by a remote server instead of a
local engine.

app.py's frame loop is clock.tick() -> engine.snapshot() -> renderer.render().
This file keeps only renderer.render(): there is no local engine and no clock
to tick, because the server owns both. Controller is wired to a
common.net.ClientProxy instead of a real GameEngine, so a click still calls
request_move/request_jump exactly as it does in app.py -- the only difference
is that the proxy serialises the call with `protocol` and sends it to the
server instead of touching a board. That is the whole point of the seam: this
file, BoardMapper and Controller needed zero changes to swap sides of the wire.

A background thread owns an asyncio event loop that talks to the server: it
receives `state` messages, decodes them, and stores the latest GameSnapshot
for the draw loop to read. Keeping that thread separate from the OpenCV loop
means a slow or stalled network never freezes the window -- the draw loop
simply keeps redrawing whatever snapshot it last saw. Sending is bridged the
other way with asyncio.run_coroutine_threadsafe, so a click on the OpenCV
thread can hand its message to the network thread's loop without blocking.

renderer.render(snapshot, elapsed_ms) needs an elapsed-ms value purely to pick
an animation frame. The client has no simulated clock any more -- game time
now lives on the server, inside the snapshot itself -- so this uses a plain
wall-clock stopwatch (time.time() since the window opened) for animation
timing only; it is cosmetic and never used to advance the game.

Run with:  python client.py
"""

import asyncio
import threading
import time

import cv2
import websockets

from common import net, protocol
from input.board_mapper import BoardMapper
from input.controller import Controller
from model.config import Config
from view.animation_set import AnimationSet
from view.img import Img
from view.observer import GameObserver
from view.renderer import Renderer
from view.score_panel import ScorePanel
from view.sprite_library import SpriteLibrary

_WINDOW = "Kung-Fu Chess (client)"
_ASSETS = "assets"
_PIECES = _ASSETS + "/pieces_mine"
_BOARD_PNG = _ASSETS + "/board.png"
_SERVER_URI = "ws://localhost:8765"

# Matches server.py's Config exactly, so the pixel positions inside every
# snapshot line up with the sprites drawn from this same crystal-board asset.
_CONFIG = Config(cell_size=98, board_offset=(13, 15))


class _ServerLink:  # pragma: no cover
    """Owns the websocket connection on its own thread and its own asyncio
    event loop, so the OpenCV draw loop never awaits anything.

    Exposes the latest decoded snapshot (None until the first one arrives)
    and a synchronous `send`, which is exactly the callable ClientProxy needs.
    """

    def __init__(self, uri):
        self._uri = uri
        self._loop = asyncio.new_event_loop()
        self._websocket = None
        self._snapshot = None
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def snapshot(self):
        with self._lock:
            return self._snapshot

    def send(self, message):
        """Called from the OpenCV thread. Schedules the send on the network
        thread's loop and returns immediately; silently drops the message if
        the connection is not up yet, mirroring how a click before the game
        starts has nothing to act on."""
        if self._websocket is None:
            return
        asyncio.run_coroutine_threadsafe(
            self._websocket.send(protocol.dumps(message)), self._loop)

    def _run(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._receive_loop())

    async def _receive_loop(self):
        async with websockets.connect(self._uri) as websocket:
            self._websocket = websocket
            async for raw in websocket:
                try:
                    message = protocol.loads(raw)
                except protocol.ProtocolError:
                    continue
                if message["type"] == protocol.STATE:
                    snapshot = protocol.decode_snapshot(message["snapshot"])
                    with self._lock:
                        self._snapshot = snapshot


class _SnapshotBoard:  # pragma: no cover
    """Controller and BoardMapper's read-only view of "the board", backed by
    the latest snapshot the server sent -- never an independent model.Board.

    The server is the single source of truth for board state: every move is
    validated and applied there, never locally. So the client must not keep
    its own Board that it updates (or fails to update) itself -- any such
    copy is only ever a guess about server state and will drift the moment a
    move lands, which is exactly the bug this class replaces (Controller was
    making selection decisions against the board's position at startup,
    forever, because nothing ever wrote a move into it). Instead every call
    here reads whatever snapshot `link` most recently received, so a
    selection or move decision is always made against the position the
    server just reported.

    Exposes only the two members Controller and BoardMapper actually read
    from a Board: piece_at(row, col) and in_bounds(row, col). Both report
    "nothing here" / "out of bounds" before the first snapshot arrives,
    which matches the draw loop drawing nothing until then -- there is
    nothing to click yet either.

    Controller.click() calls piece_at() up to twice per click (once for the
    clicked cell, once for the already-selected cell), and the network
    thread can overwrite `link`'s snapshot between those two calls -- new
    ones arrive roughly every 30ms. So the two reads can, in principle, see
    two different snapshots. This is accepted deliberately rather than
    papered over (e.g. by snapshotting once per click): the window is a few
    milliseconds, and any decision made from a torn pair of reads only ever
    produces a `move`/`jump` message, which the server -- the actual
    authority on legality -- will simply refuse if it turns out to be
    illegal. Nothing here can corrupt game state, only at worst pick a
    slightly stale selection for one click.
    """

    def __init__(self, link):
        self._link = link

    def piece_at(self, row, col):
        snapshot = self._link.snapshot()
        if snapshot is None:
            return None
        for piece in snapshot.pieces:
            if piece.row == row and piece.col == col:
                return f"{piece.color}{piece.kind}"
        return None

    def in_bounds(self, row, col):
        snapshot = self._link.snapshot()
        if snapshot is None:
            return False
        return 0 <= row < snapshot.board_height and 0 <= col < snapshot.board_width


def build_client(uri=_SERVER_URI):  # pragma: no cover
    """Compose the whole graphical stack and return the parts run() drives.
    Mirrors app.py's build_game(), except the engine is a ClientProxy, the
    board is a _SnapshotBoard instead of a model.Board, and there is a
    ServerLink instead of a GameClock."""
    link = _ServerLink(uri)
    board = _SnapshotBoard(link)
    proxy = net.ClientProxy(link.send)
    controller = Controller(proxy, BoardMapper(board, _CONFIG), board, _CONFIG)

    board_image = Img().read(_BOARD_PNG)
    image_h, image_w = board_image.img.shape[:2]

    sprites = SpriteLibrary(_PIECES, cell_size=(_CONFIG.cell_size, _CONFIG.cell_size))
    animations = AnimationSet(_PIECES)
    renderer = Renderer(sprites, lambda p: Img().read(p), _BOARD_PNG,
                        animation=animations.frame)

    observer = GameObserver(_CONFIG)
    panel = ScorePanel(observer, x=image_w + 20, y=40)
    return controller, renderer, link, observer, panel


def run():  # pragma: no cover
    """Open the window and run the frame loop until the server reports the
    game over or Esc/Q is pressed. Each frame draws whatever snapshot the
    network thread last received; nothing is drawn before the first one."""
    controller, renderer, link, observer, panel = build_client()
    link.start()
    start_time = time.time()

    def on_mouse(event, x, y, _flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN:
            controller.click(x, y)
        elif event == cv2.EVENT_RBUTTONDOWN:
            controller.jump(x, y)

    cv2.namedWindow(_WINDOW, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(_WINDOW, on_mouse)

    while True:
        snapshot = link.snapshot()
        if snapshot is not None:
            # Selection is client-side view state, not game state: it is
            # this window's own idea of what is clicked, not something the
            # game rules care about. The server never sees or broadcasts it
            # -- if it did, every client would see the opponent's selection,
            # and the server would end up tracking per-client UI state it has
            # no business owning. So it is stitched in here, after the fact,
            # into the snapshot the server actually sent.
            snapshot = snapshot._replace(selected_cell=controller.selection)
            elapsed_ms = int((time.time() - start_time) * 1000)
            observer.observe(snapshot, elapsed_ms)
            frame = renderer.render(snapshot, elapsed_ms)
            panel.draw(frame)
            cv2.imshow(_WINDOW, frame.img)
            if snapshot.game_over:
                break
        key = cv2.waitKey(16) & 0xFF
        if key in (27, ord("q")):
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    run()  # pragma: no cover
