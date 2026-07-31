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

Before the window opens, this prompts for a username on the terminal (slide
3: "Login with username -- do it in a shell, not via GUI") and sends it to
the server as the very first message on the connection, so the server can
log which username took which color. There is no password and no
persistence: this is presentation only (slide 3); the account system is a
later step. Which color this client is assigned is decided by the server
from connection order, not from anything this file sends or asserts.

Score, move log, sound and the start/end banner are wired through one
common.bus.Bus (Step 6): build_client subscribes GameObserver (frozen,
untouched -- wrapped in a lambda, never edited), client.events.GameEventSource,
client.sound.SoundPlayer and client.overlay.BannerOverlay to it, and the draw
loop below only ever calls bus.publish(topics.SNAPSHOT, snapshot) -- it never
names who reacts. Adding a future subscriber never touches this loop; that is
the whole point of routing these four through a bus instead of direct calls.

Run with:  python client.py
"""

import asyncio
import getpass
import logging
import threading
import time

import cv2
import numpy as np
import websockets

from client.events import GameEventSource
from client.overlay import BannerOverlay
from client.roomdialog import CREATE, JOIN, ask_room
from client.sound import SoundPlayer
from common import net, protocol, topics
from common.bus import Bus
from common.logsetup import add_file_logging, sanitize_for_filename
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
_SOUNDS = _ASSETS + "/sounds"
_SERVER_URI = "ws://localhost:8765"
_LOG_DIR = "logs"

_log = logging.getLogger(__name__)

# Matches server.py's Config exactly, so the pixel positions inside every
# snapshot line up with the sprites drawn from this same crystal-board asset.
_CONFIG = Config(cell_size=98, board_offset=(13, 15))


class _ServerLink:  # pragma: no cover, pylint: disable=too-many-instance-attributes
    """Owns the websocket connection on its own thread and its own asyncio
    event loop, so the OpenCV draw loop never awaits anything.

    Exposes the latest decoded snapshot (None until the first one arrives)
    and a synchronous `send`, which is exactly the callable ClientProxy needs.

    All attributes are load-bearing: the connection's identity (uri,
    username, password, room_action), its asyncio machinery (loop,
    websocket, thread), and the shared state the network thread writes and the
    OpenCV thread reads (snapshot, color, room, error, and the lock
    guarding all four). None is redundant with another, so splitting this
    further would not reduce complexity, only move it behind another name.
    """

    def __init__(self, uri, username, password, room_action=None):
        """password -- sent with `username` in the `login` message (slide
        4); see protocol.login's own docstring for what this does and does
        not protect against on an unencrypted local WebSocket.
        room_action -- None (no room: today's ordinary shared game,
        also what Play produces -- see client/roomdialog.py), or a
        (protocol.ROOM_CREATE, name) / (protocol.ROOM_JOIN, room_id) pair
        to send as the second message, right after login (slide 6)."""
        self._uri = uri
        self._username = username
        self._password = password
        self._room_action = room_action
        self._loop = asyncio.new_event_loop()
        self._websocket = None
        self._snapshot = None
        self._color = None  # None until the server's `assigned` message arrives
        self._room = None  # None unless the server sent a `room` message
        self._error = None  # None unless the server sent an `error` message
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        """Start the background thread that owns the connection."""
        self._thread.start()

    def snapshot(self):
        """-> the latest decoded GameSnapshot, or None before the first
        `state` message has arrived."""
        with self._lock:
            return self._snapshot

    def color(self):
        """-> "w" / "b" / "viewer" once the server's `assigned` message has
        arrived, or None before that -- guarded by the same lock as
        `snapshot`, since the network thread writes both."""
        with self._lock:
            return self._color

    def room(self):
        """-> the room id from the server's `room` message, or None if no
        room was requested (see room_action) or none has arrived yet --
        guarded by the same lock as `snapshot`/`color`. Sent by the server
        strictly before `assigned` on a successful room_create/room_join
        (see server.py's _handle_client), so by the time color() is no
        longer None, this is already populated whenever a room was
        requested at all."""
        with self._lock:
            return self._room

    def error(self):
        """-> the reason string from the server's `error` message, or None
        if none has arrived (yet, or ever) -- guarded by the same lock as
        `snapshot`/`color`, since the network thread writes all three. A
        server that refuses the connection (e.g. AlreadyConnectedError, or
        "room_exists"/"no_such_room" -- see server.py's _handle_client)
        sends this instead of `assigned`, so run() can tell the two apart
        before ever opening a window."""
        with self._lock:
            return self._error

    def send(self, message):
        """Called from the OpenCV thread. Schedules the send on the network
        thread's loop and returns immediately; silently drops the message if
        the connection is not up yet, mirroring how a click before the game
        starts has nothing to act on."""
        if self._websocket is None:
            _log.warning("dropped %s: not connected yet", message.get("type"))
            return
        _log.info("sending %s", message.get("type"))
        asyncio.run_coroutine_threadsafe(
            self._websocket.send(protocol.dumps(message)), self._loop)

    def _run(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._receive_loop())

    async def _receive_loop(self):
        async with websockets.connect(self._uri) as websocket:
            self._websocket = websocket
            _log.info("connected to %s", self._uri)
            # Sent here, inside the coroutine that just opened the socket,
            # rather than via the public `send` after start() returns: `send`
            # silently drops a message until `_websocket` is set (see below),
            # so sending the login from outside this loop would race the
            # connection actually being up. Sending it here, as the first
            # thing done once the socket is open, makes it always the first
            # message on the wire with no race.
            await websocket.send(
                protocol.dumps(protocol.login(self._username, self._password)))
            _log.info("login sent as %s", self._username)
            # The optional second message the server reads right after
            # login (see server.py's _read_room_choice) -- sent here, in
            # the same coroutine right after login, for the identical
            # no-race reason login itself is sent here rather than via the
            # public `send`. None (Play, or no room requested at all)
            # means nothing further is sent, exactly as before Room
            # existed -- the server's read of this is bounded by a
            # timeout for precisely that case.
            if self._room_action is not None:
                action, name = self._room_action
                message = (protocol.room_create(name) if action == protocol.ROOM_CREATE
                            else protocol.room_join(name))
                await websocket.send(protocol.dumps(message))
                _log.info("%s sent for room %s", action, name)
            async for raw in websocket:
                try:
                    message = protocol.loads(raw)
                except protocol.ProtocolError:
                    continue
                if message["type"] == protocol.STATE:
                    snapshot = protocol.decode_snapshot(message["snapshot"])
                    with self._lock:
                        self._snapshot = snapshot
                elif message["type"] == protocol.ASSIGNED:
                    with self._lock:
                        self._color = message["color"]
                    _log.info("assigned color %s", message["color"])
                elif message["type"] == protocol.ROOM:
                    with self._lock:
                        self._room = message["id"]
                    _log.info("in room %s", message["id"])
                elif message["type"] == protocol.ERROR:
                    with self._lock:
                        self._error = message["reason"]
                    _log.warning("refused by server: %s", message["reason"])
            _log.info("disconnected from %s", self._uri)


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

    piece_at also hides any piece that does not belong to this client's own
    assigned color (see piece_at's docstring for why that alone is enough to
    stop the opponent's pieces from lighting up on click, with zero changes
    to the frozen Controller).
    """

    def __init__(self, link):
        self._link = link

    def piece_at(self, row, col):
        """-> the token at (row, col), or None if there is nothing here THIS
        CLIENT may select -- which includes a cell that is merely empty, a
        cell holding the opponent's piece, and every cell at all if this
        client is a "viewer" or has no assigned color yet.

        Controller (frozen) only ever calls piece_at to decide selection: no
        piece there means nothing to select. So hiding an opponent's piece
        behind None makes it look exactly like an empty cell to Controller,
        which is enough on its own to stop it from ever being selected --
        Controller itself needed no change. Captures still work: clicking a
        cell that reads as "empty" while a piece is already selected is
        precisely Controller's request_move branch, so a capture of a
        hidden opponent piece is still sent to the server as a move, which
        the server -- the actual authority on legality -- applies or
        refuses. Rendering is unaffected by any of this: Renderer paints
        straight from the snapshot, never through this view, so the
        opponent's pieces are always drawn; only click-driven selection is
        blind to them.

        Before the server's `assigned` message arrives, this client owns no
        color yet, so every cell reads as empty rather than guessing -- the
        same treatment as being assigned "viewer"."""
        snapshot = self._link.snapshot()
        color = self._link.color()
        if snapshot is None or color is None or color == "viewer":
            return None
        for piece in snapshot.pieces:
            if piece.row == row and piece.col == col:
                return f"{piece.color}{piece.kind}" if piece.color == color else None
        return None

    def in_bounds(self, row, col):
        """-> whether (row, col) is on the board, per the latest snapshot's
        own dimensions -- False before the first snapshot arrives, since
        there is nothing to click yet either."""
        snapshot = self._link.snapshot()
        if snapshot is None:
            return False
        return 0 <= row < snapshot.board_height and 0 <= col < snapshot.board_width


_PANEL_WIDTH = 280  # extra canvas width for ScorePanel's text and the mute
#                     indicator; wide enough by eye against real rendered
#                     frames (see the manual verification for this fix).
_PANEL_LINE_H = 26  # matches view.score_panel's own _LINE_H (frozen,
#                     private to that module, so restated here rather than
#                     imported) -- gives the mute/room indicator lines
#                     above ScorePanel's own content the same rhythm, and
#                     is what keeps them from overlapping it or each other.
_PANEL_TOP = 15  # y of the first line in the panel strip (mute); room and
#                  ScorePanel each take the next _PANEL_LINE_H-sized slot
#                  below it -- see build_client and the draw loop.


def _widen_canvas(frame, extra_width):  # pragma: no cover
    """-> a new Img, `extra_width` pixels wider than `frame`, with `frame`'s
    pixels copied into the left region and a dark strip added on the right
    -- room for ScorePanel's text and the mute indicator, which app.py never
    had: board.png is 816px wide and ScorePanel is placed at
    x=image_w+20=836, off the canvas entirely. That is true in app.py too,
    so the panel has never been visible there either -- fixed here only,
    since app.py and view/ are frozen."""
    height, width, channels = frame.img.shape
    background = (30, 30, 30, 255) if channels == 4 else (30, 30, 30)
    canvas = np.empty((height, width + extra_width, channels), dtype=frame.img.dtype)
    canvas[:] = background
    canvas[:, :width] = frame.img
    widened = Img()
    widened.img = canvas
    return widened


def _draw_mute_indicator(frame, muted, x, y):  # pragma: no cover
    """Show whether sound is on or off, and the key that toggles it -- 'm'
    is otherwise undiscoverable."""
    text = "Sound: OFF (m)" if muted else "Sound: ON (m)"
    frame.put_text(text, x, y, 0.6, color=(255, 255, 255, 255))


def _draw_room_indicator(frame, room_id, x, y):  # pragma: no cover
    """Show the room id at the top of the screen -- slide 6 requires this
    for both Create and Join, so the player (and anyone they read the id
    out to) can see which room they are in. A no-op when `room_id` is
    None: Play's ordinary shared game has no room to show."""
    if room_id is None:
        return
    frame.put_text(f"Room: {room_id}", x, y, 0.6, color=(255, 255, 255, 255))


def _prompt_username():  # pragma: no cover
    """Read a non-empty username from the terminal, before the window opens
    (slide 3: login in a shell, not the GUI). Empty input (just pressing
    Enter) re-prompts rather than being sent -- there is no server-side
    validation of usernames beyond the field simply being present, so this
    is the only check there is."""
    while True:
        username = input("Username: ").strip()
        if username:
            return username


def _prompt_password():  # pragma: no cover
    """Read a password from the terminal, right after the username (slide
    4). getpass.getpass, not input(): it does not echo what is typed,
    which plain input() would -- a password visible on screen (or in a
    terminal's scrollback/recording) is exactly the kind of detail a
    reviewer notices. Unlike the username, an empty password is sent as
    typed: the server treats a brand-new username as a signup with
    whatever password arrives (slide 4: "whatever password he writes,
    that is the password"), empty string included, so there is nothing
    here to validate."""
    return getpass.getpass("Password: ")


def _client_log_path(username):  # pragma: no cover
    """-> the per-client log file path for `username`, e.g.
    "logs/client_alice.log". One file per client, not one shared
    logs/client.log: several clients on the same machine appending to a
    single file interleaves unrelated sessions with nothing to tell them
    apart, and concurrent appends from separate processes are not safe on
    Windows besides. `username` is free text typed at the terminal prompt,
    so it is sanitized first -- see sanitize_for_filename's docstring for
    exactly what that guards against."""
    return f"{_LOG_DIR}/client_{sanitize_for_filename(username)}.log"


def build_client(uri=_SERVER_URI, username="player", password="", room_action=None):  # pragma: no cover, pylint: disable=too-many-locals
    # This is the composition root: the one place that wires every
    # collaborator together, mirroring app.py's build_game(). The local
    # count reflects how many independent parts there are to wire, not
    # tangled logic -- splitting it up would just move names around, not
    # reduce what this function is responsible for building.
    """Compose the whole graphical stack and return the parts run() drives.
    Mirrors app.py's build_game(), except the engine is a ClientProxy, the
    board is a _SnapshotBoard instead of a model.Board, there is a
    ServerLink instead of a GameClock, and score/log/sound/banner are wired
    through one Bus instead of being called directly.

    password, room_action -- passed straight through to _ServerLink; see
    its docstring."""
    link = _ServerLink(uri, username, password, room_action)
    board = _SnapshotBoard(link)
    proxy = net.ClientProxy(link.send)
    controller = Controller(proxy, BoardMapper(board, _CONFIG), board, _CONFIG)

    board_image = Img().read(_BOARD_PNG)
    _image_h, image_w = board_image.img.shape[:2]

    sprites = SpriteLibrary(_PIECES, cell_size=(_CONFIG.cell_size, _CONFIG.cell_size))
    animations = AnimationSet(_PIECES)
    renderer = Renderer(sprites, lambda p: Img().read(p), _BOARD_PNG,
                        animation=animations.frame)

    observer = GameObserver(_CONFIG)
    # Two _PANEL_LINE_H slots below _PANEL_TOP -- the mute and room
    # indicators (see the draw loop) each take one of the slots above this,
    # so ScorePanel's own content starts right after both instead of
    # overlapping them (room used to be drawn on top of ScorePanel's first
    # line -- a bug found by testing Step 7).
    panel = ScorePanel(observer, x=image_w + 20, y=_PANEL_TOP + 2 * _PANEL_LINE_H)
    banner = BannerOverlay()
    sound_player = SoundPlayer(_SOUNDS)
    bus = Bus()
    # promotions is passed explicitly, the same way server.py passes
    # king_type=_CONFIG.king_type to GameRegistry instead of relying on its
    # default -- one source of truth (_CONFIG) instead of two declarations
    # of the same fact.
    event_source = GameEventSource(bus, promotions=_CONFIG.promotions)

    # elapsed_ms is a run()-loop concept (a wall-clock stopwatch); observe()
    # needs it, but the bus only ever passes one payload (the snapshot). This
    # tiny mutable box is written by run()'s loop just before every publish
    # and read by the lambda below -- the "tiny lambda supplying elapsed_ms"
    # that lets GameObserver subscribe unmodified.
    clock = {"elapsed_ms": 0}
    bus.subscribe(topics.SNAPSHOT,
                  lambda snapshot: observer.observe(snapshot, clock["elapsed_ms"]))
    bus.subscribe(topics.SNAPSHOT, event_source.on_snapshot)
    bus.subscribe(topics.SOUND, sound_player.on_sound)
    bus.subscribe(topics.GAME_START, banner.on_game_start)
    bus.subscribe(topics.GAME_END, banner.on_game_end)

    return controller, renderer, link, bus, clock, banner, panel, sound_player


def _wait_for_assignment_or_error(link, poll_interval=0.02):  # pragma: no cover
    """Block until the network thread has recorded either a seat (color()
    becomes non-None, from the server's `assigned` message) or a refusal
    (error() becomes non-None, from the server's `error` message) --
    whichever the server sends first; the two are mutually exclusive on the
    wire. Polling a plain lock-guarded field matches how the rest of
    _ServerLink is read (snapshot()/color() are read the same way, not via
    a condition variable), and this window is short: a login round-trip,
    not a whole game. Called before cv2.namedWindow, so an `error` never
    gets a window opened for it -- see run().

    Also covers a room request (slide 6) with no separate condition of its
    own: the server always sends `room` strictly before `assigned` on a
    successful room_create/room_join (see server.py's _handle_client), so
    by the time this returns ready, room() is already populated whenever a
    room was requested at all -- a room refusal arrives as `error`, same as
    every other refusal this function already waits on."""
    while link.color() is None and link.error() is None:
        time.sleep(poll_interval)


def _room_action_from_dialog(action, room_name):  # pragma: no cover
    """-> the (protocol.ROOM_CREATE | protocol.ROOM_JOIN, name) pair
    _ServerLink wants, translating roomdialog's vocabulary (CREATE/JOIN)
    into protocol's. -> None for PLAY, and, defensively, for any other
    value ask_room could not actually return -- both mean "no room", the
    same as skipping the dialog entirely (see roomdialog.ask_room's own
    docstring on when it returns PLAY)."""
    if action == CREATE:
        return protocol.ROOM_CREATE, room_name
    if action == JOIN:
        return protocol.ROOM_JOIN, room_name
    return None


def run(username, password):  # pragma: no cover, pylint: disable=too-many-locals
    # Local count grew past the threshold with the Room dialog's two
    # extra names (dialog_action, room_name) on top of what build_client
    # already returns -- one frame loop genuinely touches this many
    # independent parts; splitting it up would just move names around,
    # the same reasoning build_client's own disable above gives.
    """Show the Room dialog (slide 6), wait for the server to either seat
    this connection or refuse it, then open the window and run the frame
    loop until Esc/Q is pressed. Each frame draws whatever snapshot the
    network thread last received; nothing is drawn before the first one.

    `username`/`password` are already known by the time this is called --
    __main__ prompts for both first (slide 3/4: login in a shell, not the
    GUI) and configures per-client file logging from the username (see
    _client_log_path) before run() does anything else, so every line this
    function and everything it builds logs lands in that client's own
    file from the very first one. The Room dialog comes next, still
    before any connection is opened -- there is no Home screen in this
    project, so this is where one would have been (see
    client/roomdialog.py's module docstring).

    A refusal (e.g. AlreadyConnectedError, "bad_password", "room_exists",
    or "no_such_room" on the server) is reported on the terminal and ends
    the program before any window opens -- there would be nothing for
    that window to do, since the server never seats it, so opening one
    would just show an empty board no click can ever affect."""
    # cv2 is a compiled C extension, so pylint cannot introspect its
    # members: EVENT_LBUTTONDOWN, namedWindow, imshow, and the rest below
    # all exist and work at runtime (app.py, frozen and untouched, uses the
    # same members the same way). Every no-member warning from here to the
    # end of this function is that false positive, not a real one.
    # pylint: disable=no-member
    _log.info("client starting")
    dialog_action, room_name = ask_room()
    room_action = _room_action_from_dialog(dialog_action, room_name)
    controller, renderer, link, bus, clock, banner, panel, sound_player = \
        build_client(username=username, password=password, room_action=room_action)
    link.start()
    _wait_for_assignment_or_error(link)
    if link.error() is not None:
        print(f"Connection refused by server: {link.error()}")
        return
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
            clock["elapsed_ms"] = elapsed_ms
            bus.publish(topics.SNAPSHOT, snapshot)   # everyone reacts: score,
            #   move log, sound and the banner all subscribe in build_client.
            #   Adding a future subscriber never touches this loop -- that is
            #   the whole justification for routing these through a bus.
            frame = renderer.render(snapshot, elapsed_ms)
            banner.draw(frame, elapsed_ms)  # centered on the true board size,
            #   before the canvas is widened below -- see _widen_canvas.
            frame = _widen_canvas(frame, _PANEL_WIDTH)
            panel.draw(frame)
            panel_x = frame.img.shape[1] - _PANEL_WIDTH + 20
            _draw_mute_indicator(frame, sound_player.muted, panel_x, _PANEL_TOP)
            _draw_room_indicator(frame, link.room(),
                                  panel_x, _PANEL_TOP + _PANEL_LINE_H)
            cv2.imshow(_WINDOW, frame.img)
            # Deliberately no `if snapshot.game_over: break` here: the final
            # position, the game-over banner and the game-over sound all
            # need the window to keep drawing (and playing) to be seen and
            # heard at all -- breaking here would close it the instant the
            # king falls, before any of the three could register. The
            # player closes the window with Esc/Q below, same as always;
            # reopening the client simply joins a new game, since the
            # server already removes a finished game after its linger
            # period (common.registry.GAME_END_LINGER_MS) -- no extra code
            # needed here for that.
        key = cv2.waitKey(16) & 0xFF
        # Compared case-insensitively: cv2.waitKey returns whatever code the
        # OS reports for the physical key, which is upper-case while Caps
        # Lock is on or Shift is held -- ord("q")/ord("m") alone then never
        # match for the rest of the session, silently, with no error and no
        # visible symptom beyond "the key does nothing" (Esc still quits,
        # since 27 has no case, so this is easy to miss entirely).
        if key in (27, ord("q"), ord("Q")):
            break
        if key in (ord("m"), ord("M")):
            sound_player.toggle_mute()
        # OpenCV does not treat the window's own close ("X") button as a
        # key press -- cv2.waitKey above never sees it, so Esc/Q cannot
        # catch it. WND_PROP_VISIBLE drops below 1 the moment the OS
        # actually closes the window, which is the only signal there is
        # for that click; checked every tick, right after waitKey has had
        # its chance to pump that event.
        if cv2.getWindowProperty(_WINDOW, cv2.WND_PROP_VISIBLE) < 1:
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    # The username must be known before file logging is configured -- one
    # log file per client (see _client_log_path), not a shared
    # logs/client.log every window on this machine would interleave into.
    # Console (above) is for watching a session live; the file (below) is
    # for looking at one afterward -- slide 6 wants both, and this is what
    # makes there be a file to look at. Shared with server.py, so the two
    # log files cannot drift into different formats.
    _username = _prompt_username()
    _password = _prompt_password()
    add_file_logging(_client_log_path(_username))
    run(_username, _password)
