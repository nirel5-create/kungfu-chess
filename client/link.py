"""The websocket connection: owns it on its own thread and its own asyncio
event loop, so the OpenCV draw loop never awaits anything.
"""

import asyncio
import logging
import threading
import time
from collections import namedtuple

import websockets

from common import protocol

# How long a countdown is still considered live with no new message -- see
# _ServerLink.countdown()'s own docstring for why this cannot be 0.
_COUNTDOWN_STALE_S = 2.0

_log = logging.getLogger(__name__)

# The decoded shape of a server `history` message -- see _ServerLink.
# history() and client.panel_overlay.PanelOverlay, which reads exactly
# these five fields.
_History = namedtuple("_History", "white_name black_name white_score black_score log")


class _ServerLink:  # pragma: no cover, pylint: disable=too-many-instance-attributes
    """Exposes the latest decoded snapshot (None until the first one
    arrives) and a synchronous `send`, which is exactly the callable
    ClientProxy needs.

    All attributes are load-bearing: the connection's identity (uri,
    username, password), its asyncio machinery (loop,
    websocket, thread), and the shared state the network thread writes and the
    OpenCV thread reads (snapshot, color, room, error, and the lock
    guarding all four). None is redundant with another, so splitting this
    further would not reduce complexity, only move it behind another name.

    The room choice is deliberately NOT part of this constructor: it used
    to be sent as an automatic second message, right after login, inside
    _receive_loop. That meant the Room dialog (client/roomdialog.py, a
    real OS window a human interacts with) had to be shown and answered
    BEFORE this class even existed -- before the connection was opened,
    before login was checked -- so a rejected password was only
    discovered after the player had already filled in the dialog for
    nothing. Now login is sent alone, on connect, and client.composition.
    run() sends the room choice afterward through the ordinary public
    `send` below, once the dialog has actually closed."""

    def __init__(self, uri, username, password):
        """password -- sent with `username` in the `login` message; see
        protocol.login's own docstring for what this does and does not
        protect against on an unencrypted local WebSocket."""
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
        (see server.connection._handle_client), so by the time color() is
        no longer None, this is already populated whenever a room was
        requested at all."""
        with self._lock:
            return self._room

    def error(self):
        """-> the reason string from the server's `error` message, or None
        if none has arrived (yet, or ever) -- guarded by the same lock as
        `snapshot`/`color`, since the network thread writes all three. A
        server that refuses the connection (e.g. AlreadyConnectedError, or
        "room_exists"/"no_such_room" -- see server.connection._handle_client)
        sends this instead of `assigned`, so client.composition.run() can
        tell the two apart before ever opening a window."""
        with self._lock:
            return self._error

    def countdown(self):
        """-> the seconds remaining on the opponent's disconnect countdown,
        or None when nothing is currently counting down.

        The server only sends a `countdown` message when the second value
        changes (see server.tick) -- roughly once a second while one is
        active -- not every tick, and it never sends an explicit "cleared"
        message when the opponent reconnects; the opponent simply stops
        appearing in the per-tick broadcast. So "no message this exact
        instant" cannot mean "cleared" on its own, or this would flicker
        off between every pair of per-second updates. Instead a countdown
        is considered live as long as one was reported within
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
        for that game (see server.tick), so a caller polling this every
        frame -- see client.composition.run() -- will see it become
        non-None within a frame or two of `snapshot().game_over` turning
        True, not necessarily the exact same frame; run() waits for both
        rather than assuming they always land together."""
        with self._lock:
            return self._result

    def matchmaking_status(self):
        """-> the latest status from a `matchmaking` message ("searching",
        "found", or "timeout" -- see protocol.matchmaking's own docstring),
        or None before any has arrived. Only ever set for a connection
        that sent protocol.play() (see client.composition.run()); a
        Room/default-game connection never receives this message type at
        all, so this stays None for the whole session in that case."""
        with self._lock:
            return self._matchmaking_status

    def history(self):
        """-> the latest _History(white_name, black_name, white_score,
        black_score, log) from the server's own `history` message, or None
        before one has arrived -- read by client.panel_overlay.
        PanelOverlay, ScorePanel's adapter for this data. The server sends
        this on every change and, separately, immediately whenever this
        connection joins or reconnects (see server.connection), so a
        client that joined mid-game still sees the full log and scores
        from the very first one it receives, not just changes from that
        point on."""
        with self._lock:
            return self._history

    def rating(self):
        """-> this connection's own current ELO rating from the server's
        latest `rating` message, or None before the first one has arrived.
        The server sends this once right after a successful login and
        again, unsolicited, whenever a game this connection was part of
        ends decisively (see server.tick), so this reflects the true
        current rating for the whole session -- shown in the home dialog
        every time it reopens, including after the very game that just
        changed it -- not just a value fetched once at login."""
        with self._lock:
            return self._rating

    def waiting(self):
        """-> whether this game currently has an empty "w" or "b" seat,
        from the server's latest `waiting` message -- False before one
        has ever arrived, matching a fresh game where nobody would show
        this text yet anyway. Fixed by live testing: a solo player could
        otherwise walk a piece across an unopposed board and capture the
        other side's undefended king for a free, repeatable win, with the
        board simply looking frozen rather than explaining why. The
        server sends this only when the value CHANGES, so this reflects
        whichever state was most recently true, not necessarily "just
        now"."""
        with self._lock:
            return self._waiting

    def reset_for_new_round(self):
        """Clear every OTHER per-round field back to its fresh-connection
        value: `snapshot`, `color`, `room`, `error`, the countdown pair,
        `result`, `matchmaking_status`, and `waiting`. Called by
        client.composition.run() right before sending a new room choice
        on this SAME, still-open connection, so a value left over from
        the game that just ended -- a stale snapshot, an old result, a
        countdown, a leftover "waiting for an opponent" -- cannot flash on
        screen or be mistaken for this round's own before the server's
        first new message for it arrives.

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
            # (see server.rooms._read_room_choice) -- sent later, from
            # client.composition.run(), through the public `send` below,
            # once the Room dialog has actually closed. Not sent from here
            # any more -- see this class's own docstring for why.
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
