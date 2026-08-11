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

# How long to wait for the client's optional second message, right after
# login (see _read_room_choice) -- room_create, room_join, or protocol.
# play() (client/roomdialog.py's Play button, sent explicitly rather than
# left to a client's silence). A plain blocking read here would hang
# forever on a client that sends nothing at all (one that never
# implements the dialog), so this bounds the wait instead.
#
# Deliberately generous, not a network-round-trip guess: the client
# checks its login before ever showing the Room dialog (a real OS window
# a human answers -- see client/__main__.py's run()), and only sends this
# second message once that dialog closes. A short timeout tuned for a
# network round trip would routinely expire while a real person is still
# reading the dialog, silently defaulting them into the shared game
# instead of the room they were about to create or join. 120s is long
# enough that no one filling in a room name and clicking a button will
# ever hit it; a connection that goes quiet for that long has effectively
# been abandoned, and defaulting it to the shared game is a reasonable,
# non-hanging fallback either way.
_ROOM_MESSAGE_TIMEOUT_S = 120


async def _read_room_choice(websocket):  # pragma: no cover
    """-> (protocol.ROOM_CREATE, name), (protocol.ROOM_JOIN, room_id), or
    (protocol.PLAY, None) if the client's optional second message (right
    after login) is one of those three types within
    _ROOM_MESSAGE_TIMEOUT_S, else None. None covers two cases identically:
    a client that never implements the dialog and sends nothing at all,
    and a client that sent something this function does not recognize --
    both fall back to _find_or_create_game exactly as before Room
    existed. A malformed frame is treated the same way rather than as an
    error: at this point in the handshake the client has nothing else
    legitimate to send beyond these three, so this is defence in depth,
    the same spirit as GameSession.submit silently ignoring an
    unrecognized message type."""
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
    """The default-game policy: everyone who asks for neither a room nor
    Play shares one open game, and a new one is created when none is
    open. Play and Room replace THIS FUNCTION and nothing else -- which
    is the point of keeping it separate from GameRegistry.

    `default_game` is a single-key {"id": ...} box, owned by the
    composition root (server.composition) and threaded through the same way
    `clients` is, remembering the ONE game_id this function itself
    created for this purpose. Deliberately NOT "scan registry.game_ids()
    for any open game": a room lives in the exact same registry, keyed by
    its room name, so "any open game" would include other people's
    rooms -- reproduced live: a Play click, or a room_join that arrived a
    hair past _read_room_choice's timeout, would silently land the caller
    in someone else's still-open room. Remembering exactly the id this
    function handed out itself closes that off.

    "Open" means the game exists, is not yet game_over, AND has at least
    one currently-connected player -- UNLESS `username` already holds a
    seat in it, in which case it is "open" regardless. That exception is
    what preserves reconnecting to the default game (a disconnected
    player's seat is kept, per GameRegistry.join, precisely so they can
    come back to it -- the countdown gives that window a deadline but
    does not remove the seat before it). Without the exception, a game
    everyone had actually left is skipped (a bug found by manual testing:
    a stranger arriving at the default game used to be handed one still
    holding a seated but long-gone player, and sat there waiting for an
    opponent who was never coming back) -- a finished game is skipped the
    same way it always was, which is also why the remembered id must be
    re-checked every call rather than trusted forever."""
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
    """room_create policy: a room is exactly "a game two specific people
    agreed to meet in", and GameRegistry already keys games by id -- so
    the room id simply IS the game id, and creating a room is nothing
    more than registry.create(game_id=room_id), already-existing
    machinery. -> room_id on success. -> None if a game with that id
    already exists: two rooms may not share a name, so this must refuse
    rather than silently join the caller into someone else's room."""
    if room_id in registry.game_ids():
        return None
    game_id = registry.create(game_id=room_id)
    _log.info("created room %s", game_id)
    return game_id


def _join_room(registry, room_id):
    """room_join policy. -> room_id if a game with that id exists, else
    None -- unlike _create_room, joining never creates: a room is joined
    by its id, typed in by whoever created it and read out to whoever is
    joining, so a typo must be refused, not silently opened as a
    brand-new empty room under that name.

    Seating inside the room needs no new code at all once game_id is
    chosen here: GameRegistry.join already gives "w" to the first
    username, "b" to the second and "viewer" to everyone after."""
    if room_id not in registry.game_ids():
        return None
    return room_id
