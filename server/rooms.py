"""The Room and default-shared-game policy: reading which one a client
asked for, and turning that choice into a game_id. Play's own policy
(matchmaking) lives in server.matchmaking instead -- a Play seeker has no
game_id at all until paired, unlike Room or the default game.
"""

import asyncio
import logging

import websockets

from common import protocol

_log = logging.getLogger(__name__)

# How long to wait for the client's next room choice -- right after
# login (see _read_room_choice), and again whenever server.connection.
# _seat_for_choice loops back for a fresh one after a refused room choice
# or a timed-out Play search. A plain blocking read here would hang
# forever on a connection that never sends one, so this bounds the wait.
#
# Generous on purpose: giving up now closes the connection and tells the
# player why (protocol.IDLE_TIMEOUT) instead of silently seating them in
# a game they never chose, so firing this while a real person is still
# reading the dialog is a real cost -- log in again -- not a harmless
# default. 5 minutes covers even a slow or distracted read with room to
# spare; a connection that goes quiet that long really has been abandoned.
_ROOM_MESSAGE_TIMEOUT_S = 300


async def _read_room_choice(websocket):  # pragma: no cover
    """-> (protocol.ROOM_CREATE, name), (protocol.ROOM_JOIN, room_id), or
    (protocol.PLAY, None) if the client's next message arrives within
    _ROOM_MESSAGE_TIMEOUT_S, else None -- a timeout, a malformed frame, an
    unrecognized message, and an already-closed connection all count the
    same way; the caller decides what None means."""
    try:
        raw = await asyncio.wait_for(websocket.recv(), timeout=_ROOM_MESSAGE_TIMEOUT_S)
    except (asyncio.TimeoutError, websockets.ConnectionClosed):
        return None
    try:
        message = protocol.loads(raw)
    except protocol.ProtocolError:
        return None
    if message["type"] == protocol.ROOM_CREATE:
        return protocol.ROOM_CREATE, message["name"]
    if message["type"] == protocol.ROOM_JOIN:
        return protocol.ROOM_JOIN, message["id"]
    if message["type"] == protocol.PLAY:
        return protocol.PLAY, None
    return None


def _find_or_create_game(registry, default_game, username):
    """The default-game policy: players asking for neither a room nor
    Play share one open game, remembered in `default_game` rather than
    found by scanning the registry, since a room lives there too.
    "Open" means not game_over and has a connected player, unless
    `username` already holds a seat -- so a disconnected player returns."""
    game_id = default_game["id"]
    if game_id is not None:
        session = registry.session(game_id)
        already_seated = registry.color_of(game_id, username) is not None
        if (session is not None and not session.game_over
                and (registry.has_connected_players(game_id) or already_seated)):
            return game_id
    game_id = registry.create()
    default_game["id"] = game_id
    _log.info("created game %s", game_id)
    return game_id


def _create_room(registry, room_id):
    """room_create policy: a room's id IS its game id (GameRegistry
    already keys games by id), so creating one is just
    registry.create(game_id=room_id). -> room_id on success, -> None if
    that id already exists -- two rooms may not share a name."""
    if room_id in registry.game_ids():
        return None
    game_id = registry.create(game_id=room_id)
    _log.info("created room %s", game_id)
    return game_id


def _join_room(registry, room_id):
    """room_join policy. -> room_id if a game with that id exists, else
    None -- unlike _create_room, joining never creates: a typo must be
    refused, not silently opened as a new empty room under that name."""
    if room_id not in registry.game_ids():
        return None
    return room_id
