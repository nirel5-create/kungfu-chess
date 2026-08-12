"""One connection's whole lifetime: login, then looping it through seat
after seat (server.rooms/server.matchmaking decide which game; this module
turns that into a joined seat and runs the command loop) until it actually
disconnects. One connection now lasts for many games, not one: reusing it
across games, rather than closing and reopening between them, is what keeps
a duplicate login check (server.auth._reserve_username) from racing itself
-- that check is only released once, in _handle_client's own outer
`finally`, and a close-then-reopen sequence could plausibly race its
release and be wrongly refused as already_connected.
"""

import logging

import websockets

from common import protocol
from common.registry import AlreadyConnectedError
from common.validation import is_displayable
from server.auth import _authenticate, _current_rating, _read_login, _reserve_username
from server.history import _send_history
from server.matchmaking import _play_matchmaking
from server.rooms import _create_room, _find_or_create_game, _join_room, _read_room_choice
from server.state import Seat

_log = logging.getLogger(__name__)


async def _send_state(websocket, session):  # pragma: no cover
    await websocket.send(protocol.dumps(protocol.state(session.snapshot())))


async def _refuse(websocket, reason):  # pragma: no cover
    """Send `protocol.error(reason)`, close `websocket`, and return None --
    the shared tail of every refusal below. The caller logs first, since
    only it knows what is worth recording about this particular one."""
    await websocket.send(protocol.dumps(protocol.error(reason)))
    await websocket.close()
    return None


async def _join_or_refuse(websocket, registry, game_id, username):  # pragma: no cover
    """registry.join(game_id, username), or -- on AlreadyConnectedError --
    refuse and return None. -> the assigned color on success. This should
    be rare in practice (_reserve_username already refuses a duplicate
    login before this is reached), but GameRegistry's own per-game check
    is kept as a second guard regardless."""
    try:
        return registry.join(game_id, username)
    except AlreadyConnectedError:
        _log.warning("refused %s: already connected to game %s", username, game_id)
        return await _refuse(websocket, "already_connected")


# _seat_via_play's own sentinel: a Play search found nobody, but the
# connection stays open for it (matchmaking("timeout") already sent) --
# distinct from None (refused and closed), so _seat_for_choice's own
# loop knows to re-read a room choice and try again rather than stop.
_PLAY_TIMED_OUT = object()


async def _seat_via_play(websocket, state, username):  # pragma: no cover
    """Play's path to a seat: check GameRegistry.game_of(username) first,
    so a reconnecting player returns to a seat they still hold instead of
    being queued for a new opponent; only then falls through to
    matchmaking. -> (game_id, color) once seated, -> None once refused
    and closed, or -> _PLAY_TIMED_OUT once a search found nobody."""
    held_game_id = state.registry.game_of(username)
    if held_game_id is not None:
        color = await _join_or_refuse(websocket, state.registry, held_game_id, username)
        if color is None:
            return None
        await websocket.send(protocol.dumps(protocol.assigned(color)))
        return held_game_id, color
    matched = await _play_matchmaking(websocket, state, username)
    if matched is None:
        return _PLAY_TIMED_OUT
    return matched


async def _seat_via_room_or_default(websocket, state, username, room_choice):  # pragma: no cover
    """The other two ways to a seat: Room (create or join a named game,
    confirmed with `room` before anything else) or neither (the shared
    default game, via _find_or_create_game). -> (game_id, color) once
    joined and `assigned` sent, -> None once refused and closed."""
    if room_choice is None:
        game_id = _find_or_create_game(state.registry, state.default_game, username)
    else:
        action, room_id = room_choice
        if not is_displayable(room_id):
            _log.warning("refused %s: undisplayable room name %r", username, room_id)
            return await _refuse(websocket, "invalid_room_name")
        if action == protocol.ROOM_CREATE:
            game_id = _create_room(state.registry, room_id)
            refusal = "room_exists"
        else:
            game_id = _join_room(state.registry, room_id)
            refusal = "no_such_room"
        if game_id is None:
            _log.warning("refused %s: %s (room %s)", username, refusal, room_id)
            return await _refuse(websocket, refusal)
        await websocket.send(protocol.dumps(protocol.room(game_id)))
    color = await _join_or_refuse(websocket, state.registry, game_id, username)
    if color is None:
        return None
    await websocket.send(protocol.dumps(protocol.assigned(color)))
    return game_id, color


async def _seat_for_choice(websocket, state, username, room_choice):  # pragma: no cover
    """Turn `room_choice` into a seat: dispatches between _seat_via_play
    and _seat_via_room_or_default, and owns the retry loop neither of
    those two does -- a Play search that times out loops back to reading
    a fresh choice on the same connection instead of closing it. ->
    (game_id, color) once joined, -> None once refused and closed."""
    while True:
        if room_choice is not None and room_choice[0] == protocol.PLAY:
            seat = await _seat_via_play(websocket, state, username)
            if seat is _PLAY_TIMED_OUT:
                room_choice = await _read_room_choice(websocket)
                continue
            return seat
        return await _seat_via_room_or_default(websocket, state, username, room_choice)


async def _run_game_loop(websocket, state, seat):  # pragma: no cover
    """Register the connection, send current state and history, then read
    and apply commands until it closes or the player picks a new room/
    Play mid-session -- recognized before being handed to session.submit,
    so a player can switch rooms or start another game without closing
    the socket. -> None once closed, else the fresh room choice."""
    game_id, color, username = seat
    state.clients[websocket] = (game_id, username)
    _log.info("%s joined game %s as %s", username, game_id, color)
    try:
        await _send_state(websocket, state.registry.session(game_id))
        await _send_history(websocket, state.observers, state.registry, game_id)
        while True:
            try:
                raw = await websocket.recv()
            except websockets.ConnectionClosed:
                return None
            try:
                message = protocol.loads(raw)
            except protocol.ProtocolError:
                _log.exception("dropping malformed frame from %s in game %s",
                                username, game_id)
                continue
            message_type = message.get("type")
            if message_type == protocol.ROOM_CREATE:
                return protocol.ROOM_CREATE, message["name"]
            if message_type == protocol.ROOM_JOIN:
                return protocol.ROOM_JOIN, message["id"]
            if message_type == protocol.PLAY:
                return protocol.PLAY, None
            session = state.registry.session(game_id)
            if session is None:
                continue  # the game's linger period already elapsed
            if not state.registry.both_seated(game_id):
                # Waiting for an opponent: no move or jump is forwarded to
                # the engine at all while a seat is still empty, so no
                # motion can ever start and no capture is ever possible --
                # the client is already showing "Waiting for an opponent"
                # (protocol.waiting, see server.tick) instead of a board
                # that looks live but is not.
                _log.info("ignored %s from %s in game %s: waiting for an opponent",
                           message_type, username, game_id)
                continue
            applied = session.submit(message, state.registry.color_of(game_id, username))
            _log.info("%s %s from %s in game %s",
                       "applied" if applied else "refused", message.get("type"),
                       username, game_id)
    finally:
        state.clients.pop(websocket, None)
        state.registry.leave(game_id, username)
        _log.info("%s left game %s", username, game_id)
        if color in ("w", "b"):
            # A viewer leaving starts no countdown at all (see
            # GameRegistry.leave), so nothing to log for that case --
            # `color` is exactly the seat check that already distinguishes
            # them, already known by the caller, no extra registry query
            # needed. Started the same way whether this was a real
            # disconnect or a voluntary switch to a new room/Play: the
            # former opponent cannot tell the difference and does not
            # need to -- either way, this seat is now away.
            _log.info("countdown started for %s in game %s", username, game_id)


async def _handle_client(websocket, state):  # pragma: no cover
    """One coroutine for a connection's whole lifetime -- not one game:
    read the login, refuse outright (bad username, password, or a
    duplicate login) before touching `state.clients` or GameRegistry,
    then loop seating this connection into game after game. `username`
    is released in the outer `finally` regardless of how this ends."""
    username, password = await _read_login(websocket)
    if not is_displayable(username):
        _log.warning("refused %s: undisplayable username", username)
        return await _refuse(websocket, "invalid_username")
    if not _authenticate(state.db_conn, username, password):
        _log.warning("refused %s: bad password", username)
        return await _refuse(websocket, "bad_password")
    if not _reserve_username(state.connected_usernames, username):
        _log.warning("refused %s: already connected", username)
        return await _refuse(websocket, "already_connected")
    try:
        rating_msg = protocol.rating(_current_rating(state.db_conn, username))
        await websocket.send(protocol.dumps(rating_msg))
        room_choice = await _read_room_choice(websocket)
        while True:
            result = await _seat_for_choice(websocket, state, username, room_choice)
            if result is None:
                return
            game_id, color = result
            room_choice = await _run_game_loop(websocket, state, Seat(game_id, color, username))
            if room_choice is None:
                return
    finally:
        state.connected_usernames.discard(username)
