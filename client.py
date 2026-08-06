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

Move log, sound and the start banner are wired through one common.bus.Bus
(Step 6): build_client subscribes client.events.GameEventSource,
client.sound.SoundPlayer and client.overlay.BannerOverlay to it, and the draw
loop below only ever calls bus.publish(topics.SNAPSHOT, snapshot) -- it never
names who reacts. Adding a future subscriber never touches this loop; that is
the whole point of routing these three through a bus instead of direct calls.

Score and the move log's TEXT are the exception (Step 11): ScorePanel
(frozen) now reads client.panel_overlay.PanelOverlay, an adapter over
_ServerLink.history() -- not a client-side GameObserver computing its own log
from only the snapshots this window happened to see, which used to mean an
empty panel for anyone who joined or reconnected mid-game. The server runs
its own GameObserver per game instead (server.py) and sends the current log,
scores and names in a `history` message, so every client shows the exact
same thing.

The end banner's TEXT is the other exception: it names the winner by
username, which GameEventSource's snapshot-only view can never know (see its
own module docstring), so run() calls banner.show_result directly once the
server's own `game_over` message (_ServerLink.result()) has actually named an
outcome, rather than through the bus.

Run with:  python client.py
"""

import asyncio
import getpass
import logging
import threading
import time
from collections import namedtuple

import cv2
import numpy as np
import websockets

from client.events import GameEventSource
from client.overlay import BannerOverlay, CountdownOverlay
from client.panel_overlay import PanelOverlay
from client.roomdialog import CREATE, JOIN, PLAY, ask_room, show_no_opponent_found
from client.sound import SoundPlayer
from common import net, protocol, topics
from common.bus import Bus
from common.logsetup import add_file_logging, sanitize_for_filename
from input.board_mapper import BoardMapper
from input.controller import Controller
from model.config import Config
from view.animation_set import AnimationSet
from view.img import Img
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
# How long a countdown is still considered live with no new message -- see
# _ServerLink.countdown()'s own docstring for why this cannot be 0.
_COUNTDOWN_STALE_S = 2.0

_log = logging.getLogger(__name__)

# Matches server.py's Config exactly, so the pixel positions inside every
# snapshot line up with the sprites drawn from this same crystal-board asset.
_CONFIG = Config(cell_size=98, board_offset=(13, 15))

# The decoded shape of a server `history` message (Step 11) -- see
# _ServerLink.history() and client.panel_overlay.PanelOverlay, which reads
# exactly these five fields.
_History = namedtuple("_History", "white_name black_name white_score black_score log")


class _ServerLink:  # pragma: no cover, pylint: disable=too-many-instance-attributes
    """Owns the websocket connection on its own thread and its own asyncio
    event loop, so the OpenCV draw loop never awaits anything.

    Exposes the latest decoded snapshot (None until the first one arrives)
    and a synchronous `send`, which is exactly the callable ClientProxy needs.

    All attributes are load-bearing: the connection's identity (uri,
    username, password), its asyncio machinery (loop,
    websocket, thread), and the shared state the network thread writes and the
    OpenCV thread reads (snapshot, color, room, error, and the lock
    guarding all four). None is redundant with another, so splitting this
    further would not reduce complexity, only move it behind another name.

    The room choice (slide 6) is deliberately NOT part of this constructor
    any more: it used to be sent as an automatic second message, right
    after login, inside _receive_loop. That meant the Room dialog
    (client/roomdialog.py, a real OS window a human interacts with) had to
    be shown and answered BEFORE this class even existed -- before the
    connection was opened, before login was checked -- so a rejected
    password was only discovered after the player had already filled in
    the dialog for nothing. Now login is sent alone, on connect, and
    run() sends the room choice afterward through the ordinary public
    `send` below, once the dialog has actually closed."""

    def __init__(self, uri, username, password):
        """password -- sent with `username` in the `login` message (slide
        4); see protocol.login's own docstring for what this does and does
        not protect against on an unencrypted local WebSocket."""
        self._uri = uri
        self._username = username
        self._password = password
        self._loop = asyncio.new_event_loop()
        self._websocket = None
        self._snapshot = None
        self._color = None  # None until the server's `assigned` message arrives
        self._room = None  # None unless the server sent a `room` message
        self._error = None  # None unless the server sent an `error` message
        self._countdown_seconds = None  # None unless a countdown is live -- see countdown()
        self._countdown_updated_at = None  # time.time() of the last countdown message
        self._result = None  # (winner, winner_username) once `game_over` arrives -- see result()
        self._matchmaking_status = None  # "searching"/"found"/"timeout" -- see matchmaking_status()
        self._history = None  # _History once a `history` message arrives -- see history()
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

    def countdown(self):
        """-> the seconds remaining on the opponent's disconnect countdown
        (slide 5.2), or None when nothing is currently counting down.

        The server only sends a `countdown` message when the second value
        changes (see server.py's _tick_loop) -- roughly once a second while
        one is active -- not every tick, and it never sends an explicit
        "cleared" message when the opponent reconnects; the opponent
        simply stops appearing in the per-tick broadcast. So "no message
        this exact instant" cannot mean "cleared" on its own, or this
        would flicker off between every pair of per-second updates. Instead
        a countdown is considered live as long as one was reported within
        `_COUNTDOWN_STALE_S` -- a comfortable multiple of that ~1s cadence
        -- and considered cleared once that window has passed with nothing
        new, which is what actually happens the moment the opponent
        reconnects and the server stops sending updates for them."""
        with self._lock:
            if self._countdown_seconds is None:
                return None
            if time.time() - self._countdown_updated_at > _COUNTDOWN_STALE_S:
                return None
            return self._countdown_seconds

    def result(self):
        """-> (winner, winner_username) from the server's `game_over`
        message, or None before one has arrived. `winner` is "w"/"b"/None;
        `winner_username` is the display name for a decisive win, or None
        when `winner` is None -- no result, not a draw (Server_Design.md).

        The server sends `game_over` once, right after the last `state`
        for that game (see server.py's _tick_loop), so a caller polling
        this every frame -- see run() -- will see it become non-None
        within a frame or two of `snapshot().game_over` turning True, not
        necessarily the exact same frame; run() waits for both rather than
        assuming they always land together."""
        with self._lock:
            return self._result

    def matchmaking_status(self):
        """-> the latest status from a `matchmaking` message ("searching",
        "found", or "timeout" -- see protocol.matchmaking's own docstring),
        or None before any has arrived. Only ever set for a connection
        that sent protocol.play() (see run()); a Room/default-game
        connection never receives this message type at all, so this stays
        None for the whole session in that case."""
        with self._lock:
            return self._matchmaking_status

    def history(self):
        """-> the latest _History(white_name, black_name, white_score,
        black_score, log) from the server's own `history` message (Step
        11), or None before one has arrived -- read by
        client.panel_overlay.PanelOverlay, ScorePanel's adapter for this
        data. The server sends this on every change and, separately,
        immediately whenever this connection joins or reconnects (see
        server.py's _run_game_loop), so a client that joined mid-game
        still sees the full log and scores from the very first one it
        receives, not just changes from that point on."""
        with self._lock:
            return self._history

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
            # The room choice (protocol.PLAY / ROOM_CREATE / ROOM_JOIN) is
            # the optional second message the server reads after login
            # (see server.py's _read_room_choice) -- sent later, from
            # run(), through the public `send` below, once the Room
            # dialog has actually closed. Not sent from here any more --
            # see this class's own docstring for why.
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
                elif message["type"] == protocol.COUNTDOWN:
                    with self._lock:
                        self._countdown_seconds = message["seconds"]
                        self._countdown_updated_at = time.time()
                    _log.info("countdown: %ds", message["seconds"])
                elif message["type"] == protocol.GAME_OVER:
                    with self._lock:
                        self._result = (message["winner"], message["winner_username"])
                    _log.info("game over: winner=%s (%s)",
                              message["winner"], message["winner_username"])
                elif message["type"] == protocol.MATCHMAKING:
                    with self._lock:
                        self._matchmaking_status = message["status"]
                    _log.info("matchmaking: %s", message["status"])
                elif message["type"] == protocol.HISTORY:
                    log = protocol.decode_capture_log(message["log"])
                    with self._lock:
                        self._history = _History(
                            white_name=message["white_name"], black_name=message["black_name"],
                            white_score=message["white_score"], black_score=message["black_score"],
                            log=log)
                    _log.info("history: %d entries", len(log))
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


def build_client(uri=_SERVER_URI, username="player", password=""):  # pragma: no cover, pylint: disable=too-many-locals
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

    password -- passed straight through to _ServerLink; see its
    docstring."""
    link = _ServerLink(uri, username, password)
    board = _SnapshotBoard(link)
    proxy = net.ClientProxy(link.send)
    controller = Controller(proxy, BoardMapper(board, _CONFIG), board, _CONFIG)

    board_image = Img().read(_BOARD_PNG)
    _image_h, image_w = board_image.img.shape[:2]

    sprites = SpriteLibrary(_PIECES, cell_size=(_CONFIG.cell_size, _CONFIG.cell_size))
    animations = AnimationSet(_PIECES)
    renderer = Renderer(sprites, lambda p: Img().read(p), _BOARD_PNG,
                        animation=animations.frame)

    # Two _PANEL_LINE_H slots below _PANEL_TOP -- the mute and room
    # indicators (see the draw loop) each take one of the slots above this,
    # so ScorePanel's own content starts right after both instead of
    # overlapping them (room used to be drawn on top of ScorePanel's first
    # line -- a bug found by testing Step 7).
    #
    # Reads from PanelOverlay(link), not a real GameObserver: the server
    # runs its own GameObserver per game and sends the current log/scores/
    # names in a `history` message (Step 11), so every client shows the
    # same history -- including one that joined mid-game, which a
    # client-side GameObserver (computing its own log from only what it
    # happened to see) could never do.
    panel = ScorePanel(PanelOverlay(link), x=image_w + 20, y=_PANEL_TOP + 2 * _PANEL_LINE_H)
    banner = BannerOverlay()
    # Not wired to the bus like banner above: its number comes straight from
    # link.countdown() every frame in run()'s loop (see CountdownOverlay's
    # own docstring for why it has no state machine of its own to feed via
    # a subscriber), not from anything the server-driven SNAPSHOT/GAME_END
    # topics carry.
    countdown_overlay = CountdownOverlay()
    sound_player = SoundPlayer(_SOUNDS)
    bus = Bus()
    # promotions is passed explicitly, the same way server.py passes
    # king_type=_CONFIG.king_type to GameRegistry instead of relying on its
    # default -- one source of truth (_CONFIG) instead of two declarations
    # of the same fact.
    event_source = GameEventSource(bus, promotions=_CONFIG.promotions)

    bus.subscribe(topics.SNAPSHOT, event_source.on_snapshot)
    bus.subscribe(topics.SOUND, sound_player.on_sound)
    bus.subscribe(topics.GAME_START, banner.on_game_start)
    # Deliberately NOT bus.subscribe(topics.GAME_END, banner.on_game_end):
    # GameEventSource's own GAME_END payload is always {} (see its module
    # docstring -- it only ever sees snapshots, never who won), which is
    # all on_game_end can show ("GAME OVER", left as-is for whatever else
    # might still want that plain trigger). The server's own `game_over`
    # message names the actual winner by username, so run()'s loop calls
    # banner.show_result directly once that message has actually arrived
    # -- see run() for why it waits rather than reading link.result() from
    # inside this bus callback.

    return controller, renderer, link, bus, banner, countdown_overlay, panel, sound_player


def _wait_for_login_error(link, timeout_s=2.0, poll_interval=0.02):  # pragma: no cover
    """Block for up to `timeout_s`, or until the network thread records a
    refusal (error() becomes non-None) -- whichever is first. Called right
    after link.start(), before the Room dialog is ever shown, so a bad
    password is caught before the player wastes any effort on a dialog
    that was never going to matter. Only "bad_password" can arrive this
    early: AlreadyConnectedError (server.py's _handle_client) is scoped to
    a specific game_id, which is not known until the room choice is sent
    below, so that refusal cannot fire before this function returns --
    it is still caught, just by _wait_for_assignment_or_error afterward.

    Does NOT wait for color(): unlike _wait_for_assignment_or_error below,
    nothing has been assigned yet at this point, on purpose -- the server
    only proceeds past the login check to seat a color once it also knows
    the room choice (see server.py's _handle_client), which this function
    is called before making. `timeout_s` only needs to comfortably cover
    _authenticate's own cost (one hashed password comparison, tens of
    milliseconds) -- the server sends `error` for a bad password the
    moment it knows, with no artificial delay of its own, so this is a
    generous multiple of that, not a guess at network latency."""
    deadline = time.time() + timeout_s
    while link.error() is None and time.time() < deadline:
        time.sleep(poll_interval)


def _wait_for_assignment_or_error(link, poll_interval=0.02):  # pragma: no cover
    """Block until the network thread has recorded either a seat (color()
    becomes non-None, from the server's `assigned` message) or a refusal
    (error() becomes non-None, from the server's `error` message) --
    whichever the server sends first; the two are mutually exclusive on the
    wire. Polling a plain lock-guarded field matches how the rest of
    _ServerLink is read (snapshot()/color() are read the same way, not via
    a condition variable). Called before cv2.namedWindow, so an `error`
    never gets a window opened for it -- see run().

    Called after the room choice (protocol.PLAY/ROOM_CREATE/ROOM_JOIN) has
    already been sent -- see run() -- so this window, unlike
    _wait_for_login_error above, has no fixed bound: the server may itself
    be waiting on a slow human at the OTHER end of a room dialog (see
    server.py's _ROOM_MESSAGE_TIMEOUT_S), and there is nothing more useful
    for this end to do than keep waiting for that same human's own
    verdict.

    Also covers a room request (slide 6) with no separate condition of its
    own: the server always sends `room` strictly before `assigned` on a
    successful room_create/room_join (see server.py's _handle_client), so
    by the time this returns ready, room() is already populated whenever a
    room was requested at all -- a room refusal arrives as `error`, same as
    every other refusal this function already waits on."""
    while link.color() is None and link.error() is None:
        time.sleep(poll_interval)


def _wait_for_matchmaking_outcome(link, poll_interval=0.02):  # pragma: no cover
    """Block until Play's search (slide 5.1) resolves: matchmaking_status()
    becomes "found" or "timeout", a seat arrives directly (color() becomes
    non-None -- see below for why that is its own, equally valid way out),
    or a refusal (error()) arrives. Prints once, the moment "searching" is
    first seen, so the player is not left staring at nothing for up to the
    minute the search is allowed to run (see protocol.matchmaking's own
    docstring for the three states) -- printed here, not in run(), so the
    "only once" bookkeeping stays local to the one place that needs it.

    Only called when run() sent protocol.play() -- see its own docstring
    for why a Room/default-game connection never needs this at all.

    A returning player whose held seat is still theirs (Step 12) skips
    matchmaking entirely server-side: _handle_client sends `assigned`
    straight away, with no `matchmaking` message at all -- not "found",
    not even "searching", since nothing was actually searched for. Waiting
    only for matchmaking_status() to change would then wait forever, since
    it would stay None; color() becoming non-None is what actually signals
    a seat has arrived either way, "found" or a direct reconnect, so it is
    checked here directly rather than assuming `found` always precedes it.
    That is also why "Searching for an opponent" never gets printed for a
    reconnect: this loop exits before `status` is ever "searching", because
    it was never sent.

    Either way, the caller (run()) falls through into the ordinary
    _wait_for_assignment_or_error above once this returns, which is a
    no-op if color() is already set -- there is no second case to handle
    for "found" specifically versus a direct reconnect; both just mean
    "a seat has arrived", which is exactly what that function already
    waits for."""
    printed_searching = False
    while True:
        status = link.matchmaking_status()
        if not printed_searching and status == "searching":
            print("Searching for an opponent (up to 1 minute)...")
            printed_searching = True
        if status in ("found", "timeout") or link.color() is not None or link.error() is not None:
            return
        time.sleep(poll_interval)


def _room_message_from_dialog(action, room_name):  # pragma: no cover
    """-> the protocol message to send for the Room dialog's outcome:
    room_create/room_join for Create/Join, or protocol.play() -- slide
    5's own message, sent explicitly rather than left implicit -- for
    Play, and, defensively, for any other value ask_room could not
    actually return."""
    if action == CREATE:
        return protocol.room_create(room_name)
    if action == JOIN:
        return protocol.room_join(room_name)
    return protocol.play()


def run(username, password):
    # pragma: no cover
    # pylint: disable=too-many-locals, too-many-statements, too-many-branches
    # Local count grew past the threshold with the Room dialog's two
    # extra names (dialog_action, room_name) on top of what build_client
    # already returns -- one frame loop genuinely touches this many
    # independent parts; splitting it up would just move names around,
    # the same reasoning build_client's own disable above gives. Statement
    # and branch counts grew the same way with the winner-banner and
    # reconnect-message triggers, and Play's own three-way outcome, below:
    # each is a few linear lines read once per frame or once per run,
    # not separable logic, so splitting them into their own functions
    # would just add call overhead and more names to thread the same
    # loop-local state (elapsed_ms, snapshot, link) through.
    """Wait for the server to verify login, THEN show the Room dialog
    (slide 6) and send its outcome, wait again for the server to seat
    this connection or refuse it, then open the window and run the frame
    loop until Esc/Q is pressed. Each frame draws whatever snapshot the
    network thread last received; nothing is drawn before the first one.

    `username`/`password` are already known by the time this is called --
    __main__ prompts for both first (slide 3/4: login in a shell, not the
    GUI) and configures per-client file logging from the username (see
    _client_log_path) before run() does anything else, so every line this
    function and everything it builds logs lands in that client's own
    file from the very first one.

    Login is checked BEFORE the Room dialog is shown, not after: a manual
    test typed a wrong password, filled in the whole Create/Join/Play
    dialog, and only then saw "bad_password" -- wasted effort on a dialog
    that was never going to matter. _wait_for_login_error catches that
    (and any other login-time refusal) first; only once it finds none
    does the dialog open at all, and the dialog's outcome becomes the
    connection's second message, exactly where Room already expected it
    (see server.py's _read_room_choice) -- just sent later than it used
    to be, once a human has actually finished answering it, rather than
    automatically the instant the socket opened.

    A refusal (e.g. AlreadyConnectedError, "bad_password", "room_exists",
    or "no_such_room" on the server) is reported on the terminal and ends
    the program before any window opens -- there would be nothing for
    that window to do, since the server never seats it, so opening one
    would just show an empty board no click can ever affect.

    Play (slide 5.1) is a fourth outcome of the dialog, not a refusal: it
    can take up to a minute (common.matchmaker.SEARCH_TIMEOUT_MS) before
    the server knows whether there is an opponent at all, so this waits on
    _wait_for_matchmaking_outcome instead of the ordinary
    _wait_for_assignment_or_error until the search itself resolves --
    "found" falls through into that same ordinary wait for `assigned`, and
    so does a direct reconnect to a held seat (Step 12: a returning player
    is seated straight away, with no "found" ever sent, since nothing was
    actually searched for -- see _wait_for_matchmaking_outcome's own
    docstring for why waiting on `color()` too is what makes that not
    hang forever); "timeout" shows a message box (client/roomdialog.py's
    show_no_opponent_found, slide 5's own requirement) and exits, the same
    way any other refusal does, just via a window instead of the
    terminal."""
    # cv2 is a compiled C extension, so pylint cannot introspect its
    # members: EVENT_LBUTTONDOWN, namedWindow, imshow, and the rest below
    # all exist and work at runtime (app.py, frozen and untouched, uses the
    # same members the same way). Every no-member warning from here to the
    # end of this function is that false positive, not a real one.
    # pylint: disable=no-member
    _log.info("client starting")
    controller, renderer, link, bus, banner, countdown_overlay, panel, sound_player = \
        build_client(username=username, password=password)
    link.start()
    _wait_for_login_error(link)
    if link.error() is not None:
        print(f"Connection refused by server: {link.error()}")
        return
    dialog_action, room_name = ask_room()
    link.send(_room_message_from_dialog(dialog_action, room_name))
    if dialog_action == PLAY:
        _wait_for_matchmaking_outcome(link)
        if link.error() is not None:
            print(f"Connection refused by server: {link.error()}")
            return
        if link.matchmaking_status() == "timeout":
            show_no_opponent_found()
            return
        # Either "found" (a real match) or a direct reconnect to a held
        # seat (Step 12, no "found" ever sent) -- the server already sent
        # `assigned` either way, see _wait_for_matchmaking_outcome's own
        # docstring, so falling through into the ordinary wait below picks
        # it up with no special case of its own.
    _wait_for_assignment_or_error(link)
    if link.error() is not None:
        print(f"Connection refused by server: {link.error()}")
        return
    start_time = time.time()
    game_over_reported = False  # -> whether banner.show_result has fired
    #   for the current game yet -- see the draw loop for why this is
    #   checked every frame rather than fired once on a bus event.
    previous_countdown_seconds = None  # -> link.countdown() as of the last
    #   frame, for detecting the one transition (live -> cleared, game
    #   still in progress) that actually means the opponent reconnected --
    #   see the draw loop.

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
            bus.publish(topics.SNAPSHOT, snapshot)   # everyone reacts: move
            #   log, sound and the start banner all subscribe in
            #   build_client. Adding a future subscriber never touches this
            #   loop -- that is the whole justification for routing these
            #   through a bus. (Score/log now come from the server's own
            #   `history` message, not from a subscriber here -- see
            #   PanelOverlay/build_client's own comment on why. The end
            #   banner's text is decided below too, for the same reason.)
            if snapshot.game_over:
                if not game_over_reported:
                    result = link.result()
                    # None here means the server's `game_over` message has
                    # not arrived yet -- see result()'s own docstring on why
                    # that can lag `snapshot.game_over` by a frame or two.
                    # Simply trying again next frame, rather than falling
                    # back to a winner-less banner now, is what makes this
                    # race harmless instead of an occasional wrong display.
                    if result is not None:
                        banner.show_result(*result)
                        game_over_reported = True
            else:
                game_over_reported = False
            countdown_seconds = link.countdown()
            if (previous_countdown_seconds is not None and countdown_seconds is None
                    and not snapshot.game_over):
                # The only way a live countdown goes quiet without a
                # `game_over` message following it: the opponent's away_ms
                # was cleared by GameRegistry.join, i.e. they reconnected.
                # If the game ended instead (auto-resign, slide 5.2),
                # snapshot.game_over is already true by the time this ever
                # goes quiet -- countdown()'s own staleness window is wider
                # than one tick, so the game-over branch above always wins
                # that race, never this one.
                countdown_overlay.show_reconnected(elapsed_ms)
            previous_countdown_seconds = countdown_seconds
            frame = renderer.render(snapshot, elapsed_ms)
            banner.draw(frame, elapsed_ms)  # centered on the true board size,
            #   before the canvas is widened below -- see _widen_canvas.
            countdown_overlay.draw(frame, countdown_seconds, elapsed_ms)  # same
            #   reason: drawn over the true board, not the widened panel strip.
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
