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

Before the window opens, this prompts for a username and password on the
terminal (slide 3/4: "Login with username -- do it in a shell, not via
GUI") and sends them to the server as the very first message on the
connection. Which color a client is assigned is decided by the server
from join order, not from anything this file sends or asserts.

Step 12 (slide 3) turns run() from a straight line -- prompt, dialog, play,
exit -- into a loop: _login() retries on a refusal instead of exiting the
process, and once logged in, one _ServerLink is kept open and reused for
every game that connection ever plays: ask_room() (now the project's Home
screen, showing the logged-in username and rating) is shown again after
each game ends, and its next choice is sent on the SAME connection, never
a fresh one -- closing and reopening between games would make the
username look like a duplicate connection to the server's own check (Step
11); see server.py's own module docstring for the matching server-side
restructuring. client/homescreen.py's HomeFlow tracks which of the four
screens (LOGIN/HOME/PLAYING/QUIT) the player is on; this file is the
window/socket plumbing that drives it. Only the OpenCV window itself is
torn down and rebuilt between games (_play_one_game), not the connection
-- see build_client, which now takes an already-connected link and an
already-existing SoundPlayer instead of building either itself, so mute
state also survives across games the same way the connection does.

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
# pylint: disable=too-many-lines
# Step 12 (slide 3) grew this file past the threshold with the home
# screen's own plumbing: a login retry loop, a persistent-connection
# HOME/PLAYING loop, and the mute button's draw/hit-test wiring, each
# already broken into its own small function -- the same reasoning
# server.py's own module-level disable gives for its own Step-by-Step
# growth. Splitting this module itself is a reasonable future cleanup,
# but is not part of implementing any single step, so it is not done
# here.

import asyncio
import getpass
import logging
import threading
import time
from collections import namedtuple

import cv2
import numpy as np
import websockets

from client import mute_button
from client.events import GameEventSource
from client.homescreen import HomeFlow, QUIT
from client.overlay import BannerOverlay, CountdownOverlay
from client.panel_overlay import PanelOverlay
from client.roomdialog import (
    CREATE, JOIN, PLAY, ask_room, shutdown as shutdown_dialogs,
    show_matchmaking_progress, show_no_opponent_found,
)
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
        self._rating = None  # None until a `rating` message arrives -- see rating()
        self._waiting = False  # None-equivalent: no `waiting` has arrived yet -- see waiting()
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

    def rating(self):
        """-> this connection's own current ELO rating from the server's
        latest `rating` message (Step 12, slide 3), or None before the
        first one has arrived. The server sends this once right after a
        successful login and again, unsolicited, whenever a game this
        connection was part of ends decisively (see server.py's
        _tick_loop), so this reflects the true current rating for the
        whole session -- shown in the home dialog every time it reopens,
        including after the very game that just changed it -- not just a
        value fetched once at login."""
        with self._lock:
            return self._rating

    def waiting(self):
        """-> whether this game currently has an empty "w" or "b" seat,
        from the server's latest `waiting` message -- False before one
        has ever arrived, matching a fresh game where nobody would show
        this text yet anyway. Fixed by live testing: a solo player could
        otherwise walk a piece across an unopposed board and capture the
        other side's undefended king for a free, repeatable win, with the
        board simply looking frozen rather than explaining why (see
        server.py's own module docstring). The server sends this only
        when the value CHANGES, so this reflects whichever state was most
        recently true, not necessarily "just now"."""
        with self._lock:
            return self._waiting

    def reset_for_new_round(self):
        """Clear every OTHER per-round field back to its fresh-connection
        value: `snapshot`, `color`, `room`, `error`, the countdown pair,
        `result`, `matchmaking_status`, and `waiting`. Called by run()
        right before sending a new room choice on this SAME, still-open
        connection (Step 12), so a value left over from the game that
        just ended -- a stale snapshot, an old result, a countdown, a
        leftover "waiting for an opponent" -- cannot flash on screen or
        be mistaken for this round's own before the server's first new
        message for it arrives.

        Does NOT touch identity (uri, username, password), the asyncio
        thread/loop/websocket (all still alive and still needed -- this
        connection is being reused, not rebuilt), `history` (PanelOverlay
        reads it every frame regardless of game state, and the server
        will send a fresh one anyway, the same as every other field it
        drives), or `rating` (the home dialog shows it across rounds, and
        a round that never ends decisively sends no fresh one to replace
        it with)."""
        with self._lock:
            self._snapshot = None
            self._color = None
            self._room = None
            self._error = None
            self._countdown_seconds = None
            self._countdown_updated_at = None
            self._result = None
            self._matchmaking_status = None
            self._waiting = False

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
        # pylint: disable=too-many-statements
        # One elif per message type (STATE/ASSIGNED/ROOM/ERROR/COUNTDOWN/
        # GAME_OVER/MATCHMAKING/HISTORY/RATING/WAITING), each a couple of
        # linear lines under the same lock -- splitting this into ten
        # named handlers would just move the same lines behind ten more
        # names, not reduce what this loop is responsible for decoding.
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
                elif message["type"] == protocol.RATING:
                    with self._lock:
                        self._rating = message["rating"]
                    _log.info("rating: %d", message["rating"])
                elif message["type"] == protocol.WAITING:
                    with self._lock:
                        self._waiting = message["waiting"]
                    _log.info("waiting: %s", message["waiting"])
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
#                     imported) -- the ordinary line rhythm for every
#                     plain-text line below the mute button's own slot
#                     (room, then ScorePanel's own content), and what
#                     keeps them from overlapping each other.
_PANEL_TOP = 30  # y (text baseline) of the mute button's own line -- tall
#                  enough that its padded border box (client/mute_button.
#                  rect: _TEXT_HEIGHT + 2*_PADDING = 32px above this
#                  baseline) fits entirely on the canvas instead of
#                  running off the top edge (live-testing fix: it used to
#                  start at 15, which clipped the box's own top).
_MUTE_SLOT_H = 40  # the mute button's own padded slot height -- bigger
#                    than a plain text line's _PANEL_LINE_H, since a
#                    bordered button needs padding on every side, not
#                    just room for one line of text (live-testing fix:
#                    the room line used to sit right at _PANEL_LINE_H
#                    below the button, cramped against its padded box).
#                    The room line, and everything after it, resumes the
#                    panel's ordinary _PANEL_LINE_H rhythm from here on.


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


def _draw_mute_indicator(frame, muted, button_rect, pressed, x, y):  # pragma: no cover
                          # pylint: disable=too-many-arguments, too-many-positional-arguments
                          # pylint: disable=no-member
    # Five independent pieces this one small draw needs (mute state, the
    # button's own geometry and press state, and where to draw) -- the
    # same reasoning other disables in this file give. cv2.rectangle is a
    # compiled C extension member pylint cannot introspect -- see
    # _play_one_game's own disable for the same false positive.
    """Show whether sound is on or off, and the key that toggles it -- 'm'
    is otherwise undiscoverable. Also draws `button_rect` (client/
    mute_button.rect) as a visible bordered box, with a brief highlighted
    fill while `pressed` (client/mute_button.is_pressed) is True -- fixed
    by live testing: the control worked when clicked but looked like
    plain status text, with nothing to suggest it was clickable at all.

    The rectangle is drawn straight onto frame.img with cv2.rectangle,
    the same pattern client.py's own _widen_canvas and client/overlay.
    py's _draw_with_backing already use for the same reason: Img (frozen)
    exposes no rectangle primitive of its own."""
    left, top, right, bottom = button_rect
    channels = frame.img.shape[2]
    white = (255, 255, 255, 255) if channels == 4 else (255, 255, 255)
    if pressed:
        highlight = (90, 90, 90, 255) if channels == 4 else (90, 90, 90)
        cv2.rectangle(frame.img, (left, top), (right, bottom), highlight, thickness=-1)
    cv2.rectangle(frame.img, (left, top), (right, bottom), white, thickness=1)
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


def _prompt_username(mention_quit=False):  # pragma: no cover
    """Read a username from the terminal, before the window opens (slide
    3: login in a shell, not the GUI). -> the typed text, stripped --
    including "" (a blank Enter) or "q" unchanged, rather than re-
    prompting on either the way this used to: Step 12's _login retry
    loop treats both as "quit", and re-prompting here out from under it
    would make that way out silently not work. Any other value is a
    candidate username, with no further validation here -- there is no
    server-side check beyond the field simply being present, so this is
    the only check there ever was.

    `mention_quit` -- True only for the first prompt of a login attempt
    (live-testing fix): the way out is real on every attempt, but saying
    so again after every single refusal turned one clear line into a
    reprinted paragraph -- see _login()'s own docstring. Stating it once,
    up front, is enough for a player to remember it for the rest of the
    retry loop."""
    prompt = 'Username (blank or "q" to quit): ' if mention_quit else "Username: "
    return input(prompt).strip()


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


def _login():  # pragma: no cover
    """Prompt for username/password, retrying on a server refusal instead
    of exiting the process (Step 12: "no way to correct a typed username
    or password -- the only escape is Ctrl-C"). A fresh _ServerLink is
    built and started for every attempt -- safe, since a refused login
    never reserved anything server-side (server.py's _reserve_username is
    only ever touched after a successful _authenticate), unlike reusing a
    connection ACROSS GAMES once one has already succeeded, which is what
    the rest of this file is careful not to do (see this module's own
    docstring).

    -> (flow, link), with `flow` already logged_in() and `link` already
    started, once a login succeeds. -> (flow, None) if the player quit
    instead (see _prompt_username's own docstring for the two ways to)
    -- `flow` stays at its own fresh starting state (LOGIN), with nothing
    more for the caller to do.

    Per-client file logging is configured only once, here, right after a
    login actually succeeds -- not per attempt, so a string of failed
    attempts before the real one does not scatter log lines across
    several files, or worse, build one from a rejected, possibly-bogus
    username.

    A refusal prints just the reason (e.g. "Login refused: bad_password")
    -- live testing found the original message ("...Try again, or leave
    the username blank (or type "q") to quit.") read as a paragraph
    reprinted after every failed attempt; the way out is stated once, in
    the very first username prompt (_prompt_username's own
    mention_quit), which is enough to remember for the rest of the
    loop."""
    flow = HomeFlow()
    first_attempt = True
    while True:
        username = _prompt_username(mention_quit=first_attempt)
        first_attempt = False
        if not username or username.lower() == "q":
            return flow, None
        password = _prompt_password()
        link = _ServerLink(_SERVER_URI, username, password)
        link.start()
        _wait_for_login_error(link)
        if link.error() is None:
            add_file_logging(_client_log_path(username))
            flow.logged_in(username)
            return flow, link
        print(f"Login refused: {link.error()}")
        flow.login_refused(link.error())


def build_client(link, sound_player):  # pragma: no cover, pylint: disable=too-many-locals
    # This is the composition root: the one place that wires every
    # collaborator together, mirroring app.py's build_game(). The local
    # count reflects how many independent parts there are to wire, not
    # tangled logic -- splitting it up would just move names around, not
    # reduce what this function is responsible for building.
    """Compose the graphical stack for ONE game and return the parts
    _play_one_game drives. Mirrors app.py's build_game(), except the
    engine is a ClientProxy, the board is a _SnapshotBoard instead of a
    model.Board, there is a ServerLink instead of a GameClock, and
    score/log/sound/banner are wired through one Bus instead of being
    called directly.

    `link` and `sound_player` are built ONCE by run(), not here (Step 12):
    both must survive from game to game on the same connection -- link
    because reopening one per game would look like a duplicate login to
    the server's own check (Step 11), sound_player because muting should
    stay muted across games, not reset back to on. Everything else
    returned here (controller, renderer, bus, banner, countdown_overlay,
    panel) is rebuilt fresh every game instead: simpler than auditing each
    one for cross-game state (e.g. Controller.selection potentially
    showing a stale highlight) at negligible cost, since none of them
    owns anything that needs to outlive one game."""
    board = _SnapshotBoard(link)
    proxy = net.ClientProxy(link.send)
    controller = Controller(proxy, BoardMapper(board, _CONFIG), board, _CONFIG)

    board_image = Img().read(_BOARD_PNG)
    _image_h, image_w = board_image.img.shape[:2]

    sprites = SpriteLibrary(_PIECES, cell_size=(_CONFIG.cell_size, _CONFIG.cell_size))
    animations = AnimationSet(_PIECES)
    renderer = Renderer(sprites, lambda p: Img().read(p), _BOARD_PNG,
                        animation=animations.frame)

    # The mute button's own _MUTE_SLOT_H below _PANEL_TOP, then one
    # ordinary _PANEL_LINE_H for the room indicator (see the draw loop),
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
    panel = ScorePanel(PanelOverlay(link), x=image_w + 20,
                        y=_PANEL_TOP + _MUTE_SLOT_H + _PANEL_LINE_H)
    banner = BannerOverlay()
    # Not wired to the bus like banner above: its number comes straight from
    # link.countdown() every frame in run()'s loop (see CountdownOverlay's
    # own docstring for why it has no state machine of its own to feed via
    # a subscriber), not from anything the server-driven SNAPSHOT/GAME_END
    # topics carry.
    countdown_overlay = CountdownOverlay()
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

    return controller, renderer, bus, banner, countdown_overlay, panel


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


def _play_one_game(controller, renderer, link, bus, banner, countdown_overlay,
                    panel, sound_player):
    # pragma: no cover
    # pylint: disable=too-many-locals, too-many-statements, too-many-branches
    # pylint: disable=too-many-arguments, too-many-positional-arguments
    # pylint: disable=too-many-nested-blocks
    # One frame loop genuinely touches this many independent parts --
    # splitting it up would just move names around, the same reasoning
    # build_client's own disable gives. Statement and branch counts grew
    # the same way with the winner-banner and reconnect-message triggers,
    # the mute button's hit test, and the two ways this can end, below:
    # each is a few linear lines read once per frame, not separable
    # logic, so splitting them into their own functions would just add
    # call overhead and more names to thread the same loop-local state
    # (elapsed_ms, snapshot, mute_rect) through. The eight parameters are
    # exactly what build_client just returned plus link/sound_player --
    # one call one frame later, not a designed-in pile of unrelated
    # state. The nested-block count is `while: if snapshot: if game_over:
    # if not reported: if result:` -- each level narrows a real
    # precondition the level above it does not already rule out (a
    # snapshot to read, a game that has ended, a banner not yet queued, a
    # result actually arrived), not one flattenable decision spread
    # across several ifs.
    # cv2 is a compiled C extension, so pylint cannot introspect its
    # members: EVENT_LBUTTONDOWN, namedWindow, imshow, and the rest below
    # all exist and work at runtime (app.py, frozen and untouched, uses the
    # same members the same way). Every no-member warning from here to the
    # end of this function is that false positive, not a real one.
    # pylint: disable=no-member
    """Open the window and run one game's frame loop, from the first
    snapshot until either the player quits outright or the game ends
    naturally and its banner has finished showing. Each frame draws
    whatever snapshot the network thread last received; nothing is drawn
    before the first one.

    -> True if the player quit outright: Esc, Q, or the window's own
    close button -- run() ends the whole client either way, same as
    before Step 12. -> False once a game ended naturally (snapshot.
    game_over, the server's own `game_over` message named a result) AND
    `banner` has finished showing it: the final position, the winner
    banner and the game-over sound all still need the window to keep
    drawing (and playing) for a moment to be seen and heard at all, so
    this does not return the instant the king falls -- it reuses
    BannerOverlay's own existing `showing` timing to know when that
    moment has passed, rather than a new bespoke timer. Either way, this
    function always closes the window itself before returning, so run()
    can show the home dialog again with nothing left over from this
    game's window."""
    def on_mouse(event, x, y, _flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN:
            rect = mute_rect_holder["rect"]
            if rect is not None and mute_button.is_hit(x, y, rect):
                sound_player.toggle_mute()
                mute_pressed_holder["at_ms"] = int((time.time() - start_time) * 1000)
                return
            controller.click(x, y)
        elif event == cv2.EVENT_RBUTTONDOWN:
            controller.jump(x, y)

    # Populated on the first frame drawn below, once panel_x is known --
    # a click before that can only be a miss, since nothing is on screen
    # yet to hit. Plain dicts, not bare outer-scope variables: on_mouse
    # only reads/writes through these, never rebinds the names
    # themselves, so a bare variable would need `nonlocal` for no benefit
    # over a mutable container both closures already share by reference.
    mute_rect_holder = {"rect": None}
    mute_pressed_holder = {"at_ms": None}  # live-testing fix: elapsed_ms
    #   of the last click/keypress that toggled mute, or None before the
    #   first one this game -- see client/mute_button.is_pressed.

    cv2.namedWindow(_WINDOW, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(_WINDOW, on_mouse)

    start_time = time.time()
    game_over_reported = False  # -> whether banner.show_result has fired
    #   for this game yet -- see the draw loop for why this is checked
    #   every frame rather than fired once on a bus event.
    previous_countdown_seconds = None  # -> link.countdown() as of the last
    #   frame, for detecting the one transition (live -> cleared, game
    #   still in progress) that actually means the opponent reconnected --
    #   see the draw loop.
    quit_outright = True
    try:
        while True:
            snapshot = link.snapshot()
            if snapshot is not None:
                # Selection is client-side view state, not game state: it is
                # this window's own idea of what is clicked, not something
                # the game rules care about. The server never sees or
                # broadcasts it -- if it did, every client would see the
                # opponent's selection, and the server would end up tracking
                # per-client UI state it has no business owning. So it is
                # stitched in here, after the fact, into the snapshot the
                # server actually sent.
                snapshot = snapshot._replace(selected_cell=controller.selection)
                elapsed_ms = int((time.time() - start_time) * 1000)
                bus.publish(topics.SNAPSHOT, snapshot)   # everyone reacts:
                #   move log, sound and the start banner all subscribe in
                #   build_client. Adding a future subscriber never touches
                #   this loop -- that is the whole justification for routing
                #   these through a bus. (Score/log now come from the
                #   server's own `history` message, not from a subscriber
                #   here -- see PanelOverlay/build_client's own comment on
                #   why. The end banner's text is decided below too, for the
                #   same reason.)
                if snapshot.game_over:
                    if not game_over_reported:
                        result = link.result()
                        # None here means the server's `game_over` message
                        # has not arrived yet -- see result()'s own
                        # docstring on why that can lag snapshot.game_over
                        # by a frame or two. Simply trying again next frame,
                        # rather than falling back to a winner-less banner
                        # now, is what makes this race harmless instead of
                        # an occasional wrong display.
                        if result is not None:
                            banner.show_result(*result)
                            game_over_reported = True
                else:
                    game_over_reported = False
                countdown_seconds = link.countdown()
                if (previous_countdown_seconds is not None and countdown_seconds is None
                        and not snapshot.game_over):
                    # The only way a live countdown goes quiet without a
                    # `game_over` message following it: the opponent's
                    # away_ms was cleared by GameRegistry.join, i.e. they
                    # reconnected. If the game ended instead (auto-resign,
                    # slide 5.2), snapshot.game_over is already true by the
                    # time this ever goes quiet -- countdown()'s own
                    # staleness window is wider than one tick, so the
                    # game-over branch above always wins that race, never
                    # this one.
                    countdown_overlay.show_reconnected(elapsed_ms)
                previous_countdown_seconds = countdown_seconds
                frame = renderer.render(snapshot, elapsed_ms)
                # Read once, before draw() consumes the same pending/expiry
                # transition -- showing() is idempotent once already
                # promoted this frame, so draw()'s own internal call below
                # sees the identical text, just without needing its own
                # return value plumbed back out here.
                banner_text = banner.showing(elapsed_ms)
                banner.draw(frame, elapsed_ms)  # centered on the true board
                #   size, before the canvas is widened below -- see
                #   _widen_canvas.
                countdown_overlay.draw(frame, countdown_seconds, elapsed_ms,
                                        waiting=link.waiting())  # same
                #   reason: drawn over the true board, not the widened panel
                #   strip.
                frame = _widen_canvas(frame, _PANEL_WIDTH)
                panel.draw(frame)
                panel_x = frame.img.shape[1] - _PANEL_WIDTH + 20
                mute_rect = mute_button.rect(panel_x, _PANEL_TOP)
                mute_rect_holder["rect"] = mute_rect
                pressed = mute_button.is_pressed(elapsed_ms, mute_pressed_holder["at_ms"])
                _draw_mute_indicator(frame, sound_player.muted, mute_rect, pressed,
                                      panel_x, _PANEL_TOP)
                _draw_room_indicator(frame, link.room(),
                                      panel_x, _PANEL_TOP + _MUTE_SLOT_H)
                cv2.imshow(_WINDOW, frame.img)
                if game_over_reported and banner_text is None:
                    # The banner's own 2-second cycle has finished: the
                    # final position and the outcome have both had their
                    # moment on screen, so this game is done -- back to
                    # home (Step 12), not a break driven by any key.
                    quit_outright = False
                    break
            key = cv2.waitKey(16) & 0xFF
            # Compared case-insensitively: cv2.waitKey returns whatever
            # code the OS reports for the physical key, which is
            # upper-case while Caps Lock is on or Shift is held --
            # ord("q")/ord("m") alone then never match for the rest of the
            # session, silently, with no error and no visible symptom
            # beyond "the key does nothing" (Esc still quits, since 27 has
            # no case, so this is easy to miss entirely).
            if key in (27, ord("q"), ord("Q")):
                break
            if key in (ord("m"), ord("M")):
                sound_player.toggle_mute()
                mute_pressed_holder["at_ms"] = int((time.time() - start_time) * 1000)
            # OpenCV does not treat the window's own close ("X") button as
            # a key press -- cv2.waitKey above never sees it, so Esc/Q
            # cannot catch it. WND_PROP_VISIBLE drops below 1 the moment
            # the OS actually closes the window, which is the only signal
            # there is for that click; checked every tick, right after
            # waitKey has had its chance to pump that event.
            if cv2.getWindowProperty(_WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        cv2.destroyAllWindows()
    return quit_outright


def run():
    # pragma: no cover
    """Log in (retrying on a refusal instead of exiting the process --
    Step 12), then loop: show the home dialog (ask_room, now the
    project's Home screen -- the logged-in username and rating, and
    Create/Join/Play/Quit), send its outcome on the SAME connection
    _login already opened, wait for a seat, play one game
    (_play_one_game), and go back to the home dialog once it ends
    naturally -- until Quit is chosen or a game ends by the player
    quitting outright instead.

    Never closes and reopens the connection between games: see this
    module's own docstring for why that would look like a duplicate
    login to the server's own check (Step 11). Only the OpenCV window
    itself (_play_one_game) and the per-game UI stack (build_client) are
    rebuilt fresh each round; `link` and `sound_player` persist across
    the whole loop.

    A refusal or timeout while getting a seat (e.g. "room_exists",
    "no_such_room", or Play finding no opponent) ends the program
    outright rather than returning to the home dialog: the server closes
    the connection itself in every one of those cases (see server.py's
    _seat_for_choice and _play_matchmaking), so there is no connection
    left to reuse for another attempt -- the same terminal ending this
    client always had for these refusals, before Step 12.

    Every return path goes through a `finally` that calls roomdialog.
    shutdown() exactly once -- the one persistent Tk root every dialog in
    that module shares (see its own docstring) must be destroyed
    somewhere, and this is the one place that sees every way run() can
    end. A no-op if no dialog was ever shown (e.g. _login() itself quit
    first, before ask_room ever ran)."""
    _log.info("client starting")
    try:
        flow, link = _login()
        if link is None:
            return
        sound_player = SoundPlayer(_SOUNDS)
        while flow.state != QUIT:
            dialog_action, room_name = ask_room(username=flow.username, rating=link.rating())
            flow.chose(dialog_action, room_name)
            if flow.state == QUIT:
                break
            link.reset_for_new_round()
            link.send(_room_message_from_dialog(dialog_action, room_name))
            if dialog_action == PLAY:
                show_matchmaking_progress(link)  # live-testing fix: the
                #   search is shown, counting down, in its own small
                #   window instead of leaving the player watching nothing
                #   but a terminal line -- see its own docstring.
                if link.error() is not None:
                    print(f"Connection refused by server: {link.error()}")
                    return
                if link.matchmaking_status() == "timeout":
                    show_no_opponent_found()
                    return
                # Either "found" (a real match) or a direct reconnect to
                # a held seat (Step 12, no "found" ever sent) -- the
                # server already sent `assigned` either way, see
                # show_matchmaking_progress's own docstring, so falling
                # through into the ordinary wait below picks it up with
                # no special case of its own.
            _wait_for_assignment_or_error(link)
            if link.error() is not None:
                print(f"Connection refused by server: {link.error()}")
                return
            controller, renderer, bus, banner, countdown_overlay, panel = \
                build_client(link, sound_player)
            quit_outright = _play_one_game(controller, renderer, link, bus, banner,
                                            countdown_overlay, panel, sound_player)
            flow.game_ended()
            if quit_outright:
                return
    finally:
        shutdown_dialogs()


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    # Console (above) is for watching a session live; per-client file
    # logging (below) is for looking at one afterward -- slide 6 wants
    # both, and this is what makes there be a file to look at. Configured
    # by _login() itself, once a login actually succeeds -- see its own
    # docstring for why not here, unlike before Step 12: the username
    # a file is named after is not known, or even final, until then.
    # Shared with server.py, so the two log files cannot drift into
    # different formats.
    run()
