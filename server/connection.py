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

_log = logging.getLogger(__name__)


async def _send_state(websocket, session):  # pragma: no cover
    await websocket.send(protocol.dumps(protocol.state(session.snapshot())))


async def _join_or_refuse(websocket, registry, game_id, username):  # pragma: no cover
    """registry.join(game_id, username), or -- on AlreadyConnectedError --
    send `error`, close `websocket`, and return None. -> the assigned
    color on success. Shared by every path in _seat_for_choice that ends
    with a direct registry.join call, so the refuse-and-close sequence is
    written once. In practice this exception should not fire any more
    (the server-wide _reserve_username check already refuses a duplicate
    login before this is ever reached), but GameRegistry's own per-game
    check is kept regardless, so this still handles it correctly if it
    ever does."""
    try:
        return registry.join(game_id, username)
    except AlreadyConnectedError:
        _log.warning("refused %s: already connected to game %s", username, game_id)
        await websocket.send(protocol.dumps(protocol.error("already_connected")))
        await websocket.close()
        return None


async def _seat_for_choice(websocket, registry, default_game, matchmaker, matchmaking,
                            db_conn, username, room_choice):  # pragma: no cover
                            # pylint: disable=too-many-arguments, too-many-positional-arguments
                            # pylint: disable=too-many-return-statements
    """Turn `room_choice` -- _read_room_choice's own result, or the same
    (protocol.ROOM_CREATE, name) / (protocol.ROOM_JOIN, room_id) /
    (protocol.PLAY, None) shape _run_game_loop returns when a still-
    connected player picks again mid-session -- into a seat.

    -> (game_id, color) once joined and `assigned` already sent. -> None
    once this connection has already been refused and closed (an `error`
    already sent) -- there is nothing left for the caller to do but stop.

    A Play search that times out does NOT close the connection or return
    None: matchmaking("timeout") has already been sent by
    server.matchmaking._report_matchmaking_timeout, and this loops back
    to _read_room_choice for whatever the player picks next on the SAME
    connection, exactly as a finished game already does via
    _run_game_loop. A player who quits instead of picking again sends
    nothing, so that read simply times out on its own, same as any other
    silent disconnect this function already ends on.

    Used identically whether this is the FIRST seat this connection ever
    gets or a LATER one picked after returning home from a previous game
    on the SAME still-open connection.

    Three ways to get a seat, from `room_choice`:
    - Play: GameRegistry.game_of(username) first, in case this is a
      reconnect -- a player whose disconnect countdown is still running,
      or who simply still holds a seat, must return to that seat, not be
      queued to search for a new opponent while their own held seat sits
      there waiting for them. Only once game_of finds nothing does this
      fall through to matchmaking.
    - Room: room_create or room_join picks game_id via _create_room/
      _join_room instead of _find_or_create_game, and a chosen/created
      room is confirmed with `room` before anything else -- refused the
      same way if the name is undisplayable, already taken (create), or
      does not exist (join).
    - Neither: the ordinary shared game (_find_or_create_game)."""
    while True:
        if room_choice is not None and room_choice[0] == protocol.PLAY:
            held_game_id = registry.game_of(username)
            if held_game_id is not None:
                color = await _join_or_refuse(websocket, registry, held_game_id, username)
                if color is None:
                    return None
                await websocket.send(protocol.dumps(protocol.assigned(color)))
                return held_game_id, color
            matched = await _play_matchmaking(websocket, matchmaker, matchmaking,
                                               db_conn, username)
            if matched is None:
                room_choice = await _read_room_choice(websocket)
                continue
            return matched
        if room_choice is None:
            game_id = _find_or_create_game(registry, default_game, username)
        else:
            action, room_id = room_choice
            if not is_displayable(room_id):
                _log.warning("refused %s: undisplayable room name %r", username, room_id)
                await websocket.send(protocol.dumps(protocol.error("invalid_room_name")))
                await websocket.close()
                return None
            if action == protocol.ROOM_CREATE:
                game_id = _create_room(registry, room_id)
                refusal = "room_exists"
            else:
                game_id = _join_room(registry, room_id)
                refusal = "no_such_room"
            if game_id is None:
                _log.warning("refused %s: %s (room %s)", username, refusal, room_id)
                await websocket.send(protocol.dumps(protocol.error(refusal)))
                await websocket.close()
                return None
            await websocket.send(protocol.dumps(protocol.room(game_id)))
        color = await _join_or_refuse(websocket, registry, game_id, username)
        if color is None:
            return None
        await websocket.send(protocol.dumps(protocol.assigned(color)))
        return game_id, color


async def _run_game_loop(websocket, registry, clients, game_id,
                          color, username, observers):  # pragma: no cover
    # pylint: disable=too-many-arguments, too-many-positional-arguments
    """Register the connection in `clients`, send the current state and
    history, then read and apply commands until either the connection
    actually disconnects or the player picks a new room/Play mid-session
    -- shared by every path that ends with a seat in a game (the shared
    default game, a room, or a Play match), so there is exactly one place
    that runs the command loop and exactly one place that cleans up after
    it.

    -> None once `websocket` actually closes. -> a fresh room choice --
    the same (protocol.ROOM_CREATE, name) / (protocol.ROOM_JOIN, room_id)
    / (protocol.PLAY, None) shape _read_room_choice itself returns -- the
    moment the client sends one of those three message types, recognized
    here BEFORE being handed to session.submit so a room choice is never
    mistaken for a game command. This is what lets a player leave a room
    and create or join a different one, or start another game after one
    ends, without ever closing the underlying socket -- see
    _handle_client's own loop, which reuses the SAME connection for the
    seat this return value leads to next.

    Does NOT send `assigned`: the shared/room paths send it themselves
    right before calling this; a Play match already had it sent by
    server.tick's _seat_matched_pair, before this connection's own
    coroutine even learns which game or color it was matched to."""
    clients[websocket] = (game_id, username)
    _log.info("%s joined game %s as %s", username, game_id, color)
    try:
        await _send_state(websocket, registry.session(game_id))
        await _send_history(websocket, observers, registry, game_id)
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
            session = registry.session(game_id)
            if session is None:
                continue  # the game's linger period already elapsed
            if not registry.both_seated(game_id):
                # Waiting for an opponent: no move or jump is forwarded to
                # the engine at all while a seat is still empty, so no
                # motion can ever start and no capture is ever possible --
                # the client is already showing "Waiting for an opponent"
                # (protocol.waiting, see server.tick) instead of a board
                # that looks live but is not.
                _log.info("ignored %s from %s in game %s: waiting for an opponent",
                           message_type, username, game_id)
                continue
            applied = session.submit(message, registry.color_of(game_id, username))
            _log.info("%s %s from %s in game %s",
                       "applied" if applied else "refused", message.get("type"),
                       username, game_id)
    finally:
        clients.pop(websocket, None)
        registry.leave(game_id, username)
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


async def _handle_client(websocket, registry, clients, default_game, db_conn,
                          matchmaker, matchmaking, connected_usernames,
                          observers):  # pragma: no cover
                          # pylint: disable=too-many-arguments
                          # pylint: disable=too-many-positional-arguments
    """One coroutine for the whole lifetime of one connection -- not one
    game: read the login username/password the client sends first, then
    loop seating this same connection into game after game, via
    _seat_for_choice and _run_game_loop, until it actually disconnects.

    Three things refuse a connection outright -- an `error`, then close,
    before `clients` or GameRegistry.join is ever touched: an
    undisplayable username (is_displayable -- checked first, so a name
    cv2 cannot even draw never reaches a password check or the
    database), a wrong password (_authenticate), or a username already
    connected ANYWHERE on this server (_reserve_username -- checked next,
    before a room choice is ever read, so a duplicate login never even
    sees the Room dialog). _seat_for_choice's own docstring covers every
    refusal possible after that point.

    Once reserved, `username` is released in the outer `finally` no
    matter how this coroutine ends -- a real disconnect, a refusal partway
    through a later game choice, or an unexpected exception -- so a
    player is never locked out of their own account by a connection that
    ended abnormally.

    Sends protocol.rating right after a successful login: the home
    dialog shows it immediately, before the player has ever chosen a
    room -- see client/__main__.py's run(). server.tick sends a fresh one
    again whenever a game this connection was part of ends decisively,
    via the rating_updates hand-off list (see server.composition), so the number
    shown at home never goes stale after a game changes it."""
    username, password = await _read_login(websocket)
    if not is_displayable(username):
        _log.warning("refused %s: undisplayable username", username)
        await websocket.send(protocol.dumps(protocol.error("invalid_username")))
        await websocket.close()
        return
    if not _authenticate(db_conn, username, password):
        _log.warning("refused %s: bad password", username)
        await websocket.send(protocol.dumps(protocol.error("bad_password")))
        await websocket.close()
        return
    if not _reserve_username(connected_usernames, username):
        _log.warning("refused %s: already connected", username)
        await websocket.send(protocol.dumps(protocol.error("already_connected")))
        await websocket.close()
        return
    try:
        await websocket.send(protocol.dumps(protocol.rating(_current_rating(db_conn, username))))
        room_choice = await _read_room_choice(websocket)
        while True:
            seat = await _seat_for_choice(websocket, registry, default_game, matchmaker,
                                           matchmaking, db_conn, username, room_choice)
            if seat is None:
                return
            game_id, color = seat
            room_choice = await _run_game_loop(websocket, registry, clients, game_id, color,
                                                username, observers)
            if room_choice is None:
                return
    finally:
        connected_usernames.discard(username)
