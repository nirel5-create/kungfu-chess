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

# Identity, fixed for the whole life of the connection -- sent once, in
# _receive_loop's own login message, never touched again (not even by
# reset_for_new_round: a reused connection reuses the same login).
_Credentials = namedtuple("_Credentials", "uri username password")


class _Connection:  # pylint: disable=too-few-public-methods
    """The asyncio machinery _ServerLink's own network thread owns: its
    event loop and thread (both created once, in __init__, and never
    replaced -- this connection is reused across games, not rebuilt) and
    the websocket itself (None until _receive_loop's own `async with
    websockets.connect(...)` opens it)."""

    def __init__(self, loop, thread):
        self.loop = loop
        self.thread = thread
        self.websocket = None


class _SeatOutcome:  # pylint: disable=too-few-public-methods
    """How the current room_create/room_join/play request resolved:
    the assigned color and room -- paired, not independent, since the
    server always sends `room` strictly before `assigned` on a
    successful room_create/room_join (see _ServerLink.room()'s own
    docstring) -- or `error` instead of either on refusal (see
    _ServerLink.error()'s own docstring)."""

    def __init__(self):
        self.color = None  # None until the server's `assigned` message arrives
        self.room = None  # None unless the server sent a `room` message
        self.error = None  # None unless the server sent an `error` message


class _CountdownState:  # pylint: disable=too-few-public-methods
    """The opponent's disconnect countdown, as last reported: the whole
    seconds remaining, and when that report arrived (time.time()) --
    always read and written together, see _ServerLink.countdown()'s own
    docstring for why both are needed to decide "is this still live"."""

    def __init__(self):
        self.seconds = None
        self.updated_at = None


class _RoundState:  # pylint: disable=too-few-public-methods
    """Every _ServerLink field that resets when client.composition.run()
    sends a new room choice on this SAME, still-open connection -- see
    _ServerLink.reset_for_new_round(). Bundled into one object so
    resetting is one reassignment instead of nine, and so a value left
    over from the game that just ended cannot be mistaken for this
    round's own before the server's first new message for it arrives."""

    def __init__(self):
        self.snapshot = None
        self.seat = _SeatOutcome()
        self.countdown = _CountdownState()
        self.result = None  # (winner, winner_username) once `game_over` arrives -- see result()
        self.matchmaking_status = None  # "searching"/"found"/"timeout" -- see matchmaking_status()
        self.waiting = False  # None-equivalent: no `waiting` has arrived yet -- see waiting()


class _ServerLink:  # pragma: no cover
    """Exposes the latest decoded snapshot (None until the first one
    arrives) and a synchronous `send`, which is exactly the callable
    ClientProxy needs.

    All attributes are load-bearing: the connection's identity
    (_credentials), its asyncio machinery (_conn), the shared state the
    network thread writes and the OpenCV thread reads that resets every
    round (_round) or does not (_history, _rating), and the lock
    guarding all of the above. None is redundant with another, so
    splitting this further would not reduce complexity, only move it
    behind another name.

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
        self._credentials = _Credentials(uri, username, password)
        self._conn = _Connection(asyncio.new_event_loop(),
                                  threading.Thread(target=self._run, daemon=True))
        self._round = _RoundState()
        self._history = None  # _History once a `history` message arrives -- see history()
        self._rating = None  # None until a `rating` message arrives -- see rating()
        self._lock = threading.Lock()

    def start(self):
        """Start the background thread that owns the connection."""
        self._conn.thread.start()

    def snapshot(self):
        """-> the latest decoded GameSnapshot, or None before the first
        `state` message has arrived."""
        with self._lock:
            return self._round.snapshot

    def color(self):
        """-> "w" / "b" / "viewer" once the server's `assigned` message has
        arrived, or None before that -- guarded by the same lock as
        `snapshot`, since the network thread writes both."""
        with self._lock:
            return self._round.seat.color

    def room(self):
        """-> the room id from the server's `room` message, or None if no
        room was requested (see room_action) or none has arrived yet --
        guarded by the same lock as `snapshot`/`color`. Sent by the server
        strictly before `assigned` on a successful room_create/room_join
        (see server.connection._handle_client), so by the time color() is
        no longer None, this is already populated whenever a room was
        requested at all."""
        with self._lock:
            return self._round.seat.room

    def error(self):
        """-> the reason string from the server's `error` message, or None
        if none has arrived (yet, or ever) -- guarded by the same lock as
        `snapshot`/`color`, since the network thread writes all three. A
        server that refuses the connection (e.g. AlreadyConnectedError, or
        "room_exists"/"no_such_room" -- see server.connection._handle_client)
        sends this instead of `assigned`, so client.composition.run() can
        tell the two apart before ever opening a window."""
        with self._lock:
            return self._round.seat.error

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
            if self._round.countdown.seconds is None:
                return None
            if time.time() - self._round.countdown.updated_at > _COUNTDOWN_STALE_S:
                return None
            return self._round.countdown.seconds

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
            return self._round.result

    def matchmaking_status(self):
        """-> the latest status from a `matchmaking` message ("searching",
        "found", or "timeout" -- see protocol.matchmaking's own docstring),
        or None before any has arrived. Only ever set for a connection
        that sent protocol.play() (see client.composition.run()); a
        Room/default-game connection never receives this message type at
        all, so this stays None for the whole session in that case."""
        with self._lock:
            return self._round.matchmaking_status

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
            return self._round.waiting

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

        Does NOT touch identity (_credentials), the asyncio
        thread/loop/websocket (_conn, all still alive and still needed --
        this connection is being reused, not rebuilt), `history`
        (PanelOverlay reads it every frame regardless of game state, and
        the server will send a fresh one anyway, the same as every other
        field it drives), or `rating` (the home dialog shows it across
        rounds, and a round that never ends decisively sends no fresh one
        to replace it with)."""
        with self._lock:
            self._round = _RoundState()

    def send(self, message):
        """Called from the OpenCV thread. Schedules the send on the network
        thread's loop and returns immediately; silently drops the message if
        the connection is not up yet, mirroring how a click before the game
        starts has nothing to act on."""
        if self._conn.websocket is None:
            _log.warning("dropped %s: not connected yet", message.get("type"))
            return
        _log.info("sending %s", message.get("type"))
        asyncio.run_coroutine_threadsafe(
            self._conn.websocket.send(protocol.dumps(message)), self._conn.loop)

    def _run(self):
        asyncio.set_event_loop(self._conn.loop)
        self._conn.loop.run_until_complete(self._receive_loop())

    def _on_state(self, message):
        snapshot = protocol.decode_snapshot(message["snapshot"])
        with self._lock:
            self._round.snapshot = snapshot

    def _on_assigned(self, message):
        with self._lock:
            self._round.seat.color = message["color"]
        _log.info("assigned color %s", message["color"])

    def _on_room(self, message):
        with self._lock:
            self._round.seat.room = message["id"]
        _log.info("in room %s", message["id"])

    def _on_error(self, message):
        with self._lock:
            self._round.seat.error = message["reason"]
        _log.warning("refused by server: %s", message["reason"])

    def _on_countdown(self, message):
        with self._lock:
            self._round.countdown.seconds = message["seconds"]
            self._round.countdown.updated_at = time.time()
        _log.info("countdown: %ds", message["seconds"])

    def _on_game_over(self, message):
        with self._lock:
            self._round.result = (message["winner"], message["winner_username"])
        _log.info("game over: winner=%s (%s)",
                  message["winner"], message["winner_username"])

    def _on_matchmaking(self, message):
        with self._lock:
            self._round.matchmaking_status = message["status"]
        _log.info("matchmaking: %s", message["status"])

    def _on_history(self, message):
        log = protocol.decode_capture_log(message["log"])
        with self._lock:
            self._history = _History(
                white_name=message["white_name"], black_name=message["black_name"],
                white_score=message["white_score"], black_score=message["black_score"],
                log=log)
        _log.info("history: %d entries", len(log))

    def _on_rating(self, message):
        with self._lock:
            self._rating = message["rating"]
        _log.info("rating: %d", message["rating"])

    def _on_waiting(self, message):
        with self._lock:
            self._round.waiting = message["waiting"]
        _log.info("waiting: %s", message["waiting"])

    # One entry per message type the server ever sends (STATE/ASSIGNED/
    # ROOM/ERROR/COUNTDOWN/GAME_OVER/MATCHMAKING/HISTORY/RATING/WAITING),
    # each already its own small handler above -- a dispatch table instead
    # of one flat if/elif chain, so _receive_loop below is just "look up
    # and call". A class attribute, not built per instance: every
    # _ServerLink dispatches the same way, and building it once avoids
    # re-binding ten methods on every single connection.
    _HANDLERS = {
        protocol.STATE: _on_state,
        protocol.ASSIGNED: _on_assigned,
        protocol.ROOM: _on_room,
        protocol.ERROR: _on_error,
        protocol.COUNTDOWN: _on_countdown,
        protocol.GAME_OVER: _on_game_over,
        protocol.MATCHMAKING: _on_matchmaking,
        protocol.HISTORY: _on_history,
        protocol.RATING: _on_rating,
        protocol.WAITING: _on_waiting,
    }

    async def _receive_loop(self):
        async with websockets.connect(self._credentials.uri) as websocket:
            self._conn.websocket = websocket
            _log.info("connected to %s", self._credentials.uri)
            # Sent here, inside the coroutine that just opened the socket,
            # rather than via the public `send` after start() returns: `send`
            # silently drops a message until `_conn.websocket` is set (see
            # below), so sending the login from outside this loop would
            # race the connection actually being up. Sending it here, as
            # the first thing done once the socket is open, makes it
            # always the first message on the wire with no race.
            await websocket.send(protocol.dumps(
                protocol.login(self._credentials.username, self._credentials.password)))
            _log.info("login sent as %s", self._credentials.username)
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
                handler = self._HANDLERS.get(message["type"])
                if handler is not None:
                    handler(self, message)
            _log.info("disconnected from %s", self._credentials.uri)
