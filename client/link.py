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

# How long a countdown is still considered live with no new message.
_COUNTDOWN_STALE_S = 2.0

_log = logging.getLogger(__name__)

# The decoded shape of a server `history` message; client.panel_overlay.
# PanelOverlay reads these five fields directly.
_History = namedtuple("_History", "white_name black_name white_score black_score log")

# Identity, fixed for the life of the connection: never reassigned, not
# even by reset_for_new_round, since a reused connection reuses the same
# login.
_Credentials = namedtuple("_Credentials", "uri username password")


class _Connection:  # pylint: disable=too-few-public-methods
    """The asyncio machinery the network thread owns: its event loop and
    thread (created once, never replaced -- this connection is reused
    across games, not rebuilt) and the websocket itself (None until
    `_receive_loop` opens it)."""

    def __init__(self, loop, thread):
        self.loop = loop
        self.thread = thread
        self.websocket = None


class _SeatOutcome:  # pylint: disable=too-few-public-methods
    """How the current room_create/room_join/play request resolved: color
    and room are paired, not independent, since the server always sends
    `room` strictly before `assigned` on success -- or `error` instead of
    either on refusal."""

    def __init__(self):
        self.color = None  # None until the server's `assigned` message arrives
        self.room = None  # None unless the server sent a `room` message
        self.error = None  # None unless the server sent an `error` message


class _CountdownState:  # pylint: disable=too-few-public-methods
    """The opponent's disconnect countdown, as last reported: the whole
    seconds remaining, and when that report arrived (time.time()) --
    always read and written together, since both are needed to decide
    whether the countdown is still live."""

    def __init__(self):
        self.seconds = None
        self.updated_at = None


class _RoundState:  # pylint: disable=too-few-public-methods
    """Every _ServerLink field that resets for a new round on the same,
    still-open connection. Bundled into one object so resetting is a
    single reassignment instead of nine, and a value left over from the
    game that just ended cannot be mistaken for this round's own before
    the server's first new message arrives."""

    def __init__(self):
        self.snapshot = None
        self.seat = _SeatOutcome()
        self.countdown = _CountdownState()
        self.result = None  # (winner, winner_username) once `game_over` arrives
        self.matchmaking_status = None  # "searching"/"found"/"timeout"
        self.waiting = False  # None-equivalent: no `waiting` has arrived yet


class _ServerLink:  # pragma: no cover
    """Owns the connection: exposes the latest decoded snapshot (None
    until the first one arrives) and a synchronous `send`. The room
    choice is sent separately from login, once the Room dialog has
    closed, so a rejected password is discovered before the player fills
    in a dialog that was never going to matter."""

    def __init__(self, uri, username, password):
        """`password` is sent with `username` in the plaintext `login`
        message; this is not protection against anything beyond a casual
        glance on an unencrypted local WebSocket."""
        self._credentials = _Credentials(uri, username, password)
        self._conn = _Connection(asyncio.new_event_loop(),
                                  threading.Thread(target=self._run, daemon=True))
        self._round = _RoundState()
        self._history = None  # _History once a `history` message arrives
        self._rating = None  # None until a `rating` message arrives
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
        room was requested or none has arrived yet -- guarded by the same
        lock as `snapshot`/`color`. Sent by the server strictly before
        `assigned`, so this is already populated by the time color() is
        no longer None, whenever a room was requested at all."""
        with self._lock:
            return self._round.seat.room

    def error(self):
        """-> the reason string from the server's `error` message, or None
        if none has arrived -- guarded by the same lock as
        `snapshot`/`color`. A server that refuses the connection sends
        this instead of `assigned`, so callers can tell the two apart
        before ever opening a window."""
        with self._lock:
            return self._round.seat.error

    def countdown(self):
        """-> seconds remaining on the opponent's disconnect countdown, or
        None when none is active. The server sends `countdown` only on
        change, with no explicit "cleared" message, so this is treated as
        live only within `_COUNTDOWN_STALE_S` of the last report."""
        with self._lock:
            if self._round.countdown.seconds is None:
                return None
            if time.time() - self._round.countdown.updated_at > _COUNTDOWN_STALE_S:
                return None
            return self._round.countdown.seconds

    def result(self):
        """-> (winner, winner_username) from the server's `game_over`
        message, or None before one has arrived. `winner_username` is set
        only for a decisive win, never a draw. Sent once, right after the
        final `state`, so this may turn non-None a frame or two after
        `snapshot().game_over` turns True, not necessarily the same one."""
        with self._lock:
            return self._round.result

    def matchmaking_status(self):
        """-> the latest status from a `matchmaking` message ("searching",
        "found", or "timeout"), or None before any has arrived. Only ever
        set for a connection that requested matchmaking; a Room/default-
        game connection never receives this message type at all."""
        with self._lock:
            return self._round.matchmaking_status

    def history(self):
        """-> the latest _History(white_name, black_name, white_score,
        black_score, log), or None before one has arrived. The server
        resends this on every change and also immediately on join or
        reconnect, so a client that joins mid-game still sees the full
        log and scores from its first message, not just later changes."""
        with self._lock:
            return self._history

    def rating(self):
        """-> this connection's own current ELO rating from the server's
        latest `rating` message, or None before the first one has
        arrived. Sent once after login and again whenever a game this
        connection was part of ends decisively, so it reflects the true
        current rating even right after the game that just changed it."""
        with self._lock:
            return self._rating

    def waiting(self):
        """-> whether this game currently has an empty seat, from the
        server's latest `waiting` message -- False before one arrives.
        Without this, a solo player could capture the other side's
        undefended king while the board simply looked frozen. Sent only
        on change, so this is whichever value was most recently true."""
        with self._lock:
            return self._round.waiting

    def reset_for_new_round(self):
        """Clear every per-round field back to its fresh-connection value,
        so nothing left over from the game that just ended can flash on
        screen before the new round's first message arrives. Identity,
        the connection machinery, `history`, and `rating` are left alone:
        this connection is reused, not rebuilt."""
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

    # A dispatch table instead of a flat if/elif chain, so _receive_loop
    # below is just "look up and call". A class attribute, not built per
    # instance, so it is built once rather than re-bound on every
    # connection.
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
            # rather than via the public `send`: `send` silently drops a
            # message until `_conn.websocket` is set, so sending the login
            # from outside this loop would race the connection being up.
            await websocket.send(protocol.dumps(
                protocol.login(self._credentials.username, self._credentials.password)))
            _log.info("login sent as %s", self._credentials.username)
            # The room choice is sent later, through the public `send`
            # below, once the Room dialog has closed -- not from here.
            async for raw in websocket:
                try:
                    message = protocol.loads(raw)
                except protocol.ProtocolError:
                    continue
                handler = self._HANDLERS.get(message["type"])
                if handler is not None:
                    handler(self, message)
            _log.info("disconnected from %s", self._credentials.uri)
