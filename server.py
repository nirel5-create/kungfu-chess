"""Async WebSocket server for Kung-Fu Chess.

app.py's local frame loop is clock.tick() -> engine.snapshot() ->
renderer.render(). This file keeps the first half of that loop -- the clock
and the engine -- and moves the second half to whichever clients are
connected: every ~30 ms it advances every live game and broadcasts each
game's protocol.state(session.snapshot()) to the clients sitting in that
game, so each window redraws the same board as the others in its game.
Commands travel the other way: a client sends a `move`/`jump` message, this
file decodes it with protocol.loads and hands it to GameSession.submit -- it
never builds or applies a command itself.

What this file owns: the websocket connections, the tick interval, and
broadcasting. What it does NOT own: which games exist, seats, or lifecycle --
that is common.registry.GameRegistry; nor game rules or command handling --
that is common.net.GameSession, one layer below the registry. This file is
plumbing only, and is not unit-tested, the same way app.py's real OpenCV
window is not: a live socket cannot be driven from a test without becoming
an integration test. GameRegistry and GameSession are fully covered by
tests/unit/test_registry.py and tests/unit/test_session.py.

Step 5 fixes a real bug: this file used to build ONE GameSession at startup
and keep it forever, so once its king fell every later arrival got a
permanently-finished game and closed immediately. Now the server holds MANY
games via GameRegistry, and _find_or_create_game (below) is a small, clearly
separate policy function that decides which game a new connection joins --
today, everyone shares one open game, creating a fresh one when none is
open. Play (slide 5) and Room (slide 6) will later replace only that one
function; GameRegistry itself needs no change for either.

Colors are assigned by GameRegistry.join, by connection order within a game
(Step 4): the first to join a game is seated "w", the second "b", and any
later joiner becomes a "viewer" that can watch but never move. This is the
"server knows WHO you are" half of the ownership design in common.net --
GameSession.submit is the half that enforces it.

At startup this also connects to Postgres (common.db) and makes sure the
players schema exists (Step A). Step 8 (slide 4) is what actually uses that
connection while the server is running: a client's `login` now carries a
password too, checked (or, for a brand-new username, created) against
common.db before a seat is ever handed out, and every decisive game's
GAME_END updates both players' ELO rating (common.elo) through the exact
same subscriber pattern already used to log the winner -- no change to
GameRegistry, which is what the bus was built for. Live games still do not
depend on the database: a failed connection, at startup or later, is
logged and the server (and every login) keeps working regardless -- see
_connect_db, _authenticate, and _update_ratings_on_game_end.

Run with:  python server.py
"""

import asyncio
import logging

import websockets

from common import db, elo, net, protocol, topics
from common.bus import Bus
from common.logsetup import add_file_logging
from common.registry import AlreadyConnectedError, GameRegistry
from engine.game import GameEngine
from model.board import Board
from model.config import Config

# "localhost" binds only to the loopback interface *inside* whatever network
# namespace the process runs in. On the host that is fine -- the interface a
# local client connects to and the one the server binds to are the same
# loopback. Inside a container it is not: Docker's published port
# (docker-compose.yml `ports: ["8765:8765"]`) forwards an external
# connection onto the container's real network interface, not its loopback,
# so a server bound only to loopback never sees that connection -- the
# client gets a TCP connection that opens and then closes with zero bytes,
# exactly the failure this was. Binding to 0.0.0.0 listens on every
# interface instead, including the one Docker forwards to. This is safe
# here specifically because Docker only exposes to the host the ports this
# project's own docker-compose.yml explicitly publishes -- 0.0.0.0 inside
# the container is not the same exposure as 0.0.0.0 on a bare host.
_HOST = "0.0.0.0"
_PORT = 8765
_TICK_MS = 30
_LOG_PATH = "logs/server.log"
# Not the per-tick state broadcast itself -- that is ~33 lines/second and
# would make the log file useless within seconds (slide 6 asks for logs
# that can be inspected afterward, not a firehose). A summary every 10s is
# enough to show the loop is alive without doing that.
_SUMMARY_INTERVAL_MS = 10_000

# How long to wait for the client's optional second message, right after
# login (see _read_room_choice) -- room_create, room_join, or protocol.
# play() (client/roomdialog.py's Play button, sent explicitly rather than
# left to a client's silence). A plain blocking read here would hang
# forever on a client that sends nothing at all (one that never
# implements the dialog), so this bounds the wait instead.
#
# Deliberately generous, not a network-round-trip guess: the client now
# checks its login before ever showing the Room dialog (a real OS window
# a human answers -- see client.py's run()), and only sends this second
# message once that dialog closes. A short timeout tuned for a network
# round trip would routinely expire while a real person is still reading
# the dialog, silently defaulting them into the shared game instead of
# the room they were about to create or join -- that used to be safe to
# ignore only because the dialog was answered BEFORE the connection even
# opened. 120s is long enough that no one filling in a room name and
# clicking a button will ever hit it; a connection that goes quiet for
# that long has effectively been abandoned, and defaulting it to the
# shared game is a reasonable, non-hanging fallback either way.
_ROOM_MESSAGE_TIMEOUT_S = 120

# Matches app.py's build_game(): the crystal board asset has a thin decorative
# frame, so cells are 98px and the first cell starts 13px in, 15px down. The
# client draws with the same asset, so the pixel positions in every snapshot
# only line up if both sides use this same Config.
_CONFIG = Config(cell_size=98, board_offset=(13, 15))

_START = [
    ["bR", "bN", "bB", "bQ", "bK", "bB", "bN", "bR"],
    ["bP", "bP", "bP", "bP", "bP", "bP", "bP", "bP"],
    [".", ".", ".", ".", ".", ".", ".", "."],
    [".", ".", ".", ".", ".", ".", ".", "."],
    [".", ".", ".", ".", ".", ".", ".", "."],
    [".", ".", ".", ".", ".", ".", ".", "."],
    ["wP", "wP", "wP", "wP", "wP", "wP", "wP", "wP"],
    ["wR", "wN", "wB", "wQ", "wK", "wB", "wN", "wR"],
]

_log = logging.getLogger(__name__)


def _build_session():  # pragma: no cover
    board = Board([row[:] for row in _START], _CONFIG)
    engine = GameEngine(board, _CONFIG)
    return net.GameSession(engine)


async def _send_state(websocket, session):  # pragma: no cover
    await websocket.send(protocol.dumps(protocol.state(session.snapshot())))


async def _read_login(websocket):  # pragma: no cover
    """The (username, password) from the client's first message (a
    `login`), or ("?", "") if the connection closes or sends something
    else before logging in. A missing/malformed login never blocks a seat
    from being assigned -- there being no account to check a password
    against is treated the same as a real "?" account always was, before
    Step 8."""
    try:
        raw = await websocket.recv()
        message = protocol.loads(raw)
    except (protocol.ProtocolError, websockets.ConnectionClosed):
        return "?", ""
    if message.get("type") != protocol.LOGIN:
        return "?", ""
    return message["username"], message["password"]


def _authenticate(db_conn, username, password):  # pragma: no cover
    """-> whether `username`/`password` should be let in. A brand-new
    username creates the account at common.db.DEFAULT_RATING (slide 4:
    "first time, whatever password he writes, that is the password"); an
    existing one must match what create_player already refused to
    overwrite.

    -> True unconditionally when `db_conn` is None (Postgres unreachable
    at startup, see _connect_db) or when the check itself raises
    (unreachable mid-session) -- Server_Design.md promises live games do
    not depend on Postgres, and this is where that promise is either kept
    or broken: a database outage must not lock every player out, only
    skip the one check it cannot perform."""
    if db_conn is None:
        return True
    try:
        if db.create_player(db_conn, username, password):
            return True
        return db.verify_password(db_conn, username, password)
    except Exception as exc:  # pylint: disable=broad-except
        # Deliberate, same reasoning as _connect_db's own broad except:
        # any failure here (connection dropped mid-session, Postgres
        # restarting) must not turn into a rejected login -- expected and
        # handled, not a crash, which is exactly why this is a one-line
        # warning naming the reason rather than _log.exception's full
        # traceback: a stack trace here would misrepresent a handled
        # condition as one, and train a reader to skim past a real one.
        _log.warning("password check failed for %s (%s); letting them in, "
                     "play continues without the database", username, exc)
        return True


async def _read_room_choice(websocket):  # pragma: no cover
    """-> (protocol.ROOM_CREATE, name) or (protocol.ROOM_JOIN, room_id) if
    the client's optional second message (right after login) is one of
    those two types within _ROOM_MESSAGE_TIMEOUT_S, else None. None covers
    three cases identically: an explicit protocol.play() (client/
    roomdialog.py's Play button), a client that never implements the
    dialog and sends nothing at all, and a client that sent something
    this function does not recognize -- all fall back to
    _find_or_create_game exactly as before Room existed, per
    STEP7_ROOMS.md. A malformed frame is treated the same way rather than
    as an error: at this point in the handshake the client has nothing
    else legitimate to send beyond these three, so this is defence in
    depth, the same spirit as GameSession.submit silently ignoring an
    unrecognized
    message type."""
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
    return None


def _find_or_create_game(registry, default_game):
    """This step's placeholder policy: everyone shares one open game, and a
    new one is created when none is open. Play (slide 5, its actual name
    once STEP7_ROOMS.md's follow-up fixes renamed the dialog's Cancel
    button -- see client/roomdialog.py) and Room (slide 6) replace THIS
    FUNCTION and nothing else -- which is the point of keeping it separate
    from GameRegistry.

    `default_game` is a single-key {"id": ...} box, owned by _main() and
    threaded through the same way `clients` is, remembering the ONE
    game_id this function itself created for this purpose. Deliberately
    NOT "scan registry.game_ids() for any open game", which is what this
    function used to do before Room existed, when every game in the
    registry WAS by definition the one shared game and that scan was
    harmless. It is not harmless any more: a room lives in the exact same
    registry, keyed by its room name, and "any open game" then includes
    other people's rooms. That is precisely the bug this fixes --
    reproduced live: a Play click, or a room_join that arrived a hair
    past _read_room_choice's timeout, would silently land the caller in
    someone else's still-open room -- sometimes as an unwanted extra
    viewer (nothing to move), sometimes even in a
    playable seat of a room they never asked to join. Remembering
    exactly the id this function handed out itself, rather than
    re-deriving "the" shared game by scanning, closes that off: a room's
    id is never guessed at here regardless of how the registry's
    contents change.

    "Open" means the game exists and is not yet game_over; a finished
    game is skipped (the same original bug fix this function has always
    made -- a new arrival never gets handed a permanently-ended game),
    which is also why the remembered id must be re-checked every call
    rather than trusted forever."""
    game_id = default_game["id"]
    if game_id is not None:
        session = registry.session(game_id)
        if session is not None and not session.game_over:
            return game_id
    game_id = registry.create()
    default_game["id"] = game_id
    _log.info("created game %s", game_id)
    return game_id


def _create_room(registry, room_id):
    """room_create policy (slide 6): a room is exactly "a game two specific
    people agreed to meet in", and GameRegistry already keys games by id --
    so the room id simply IS the game id, and creating a room is nothing
    more than registry.create(game_id=room_id), already-existing machinery.
    -> room_id on success. -> None if a game with that id already exists --
    the mentor was explicit that two rooms may not share a name, so this
    must refuse rather than silently join the caller into someone else's
    room."""
    if room_id in registry.game_ids():
        return None
    game_id = registry.create(game_id=room_id)
    _log.info("created room %s", game_id)
    return game_id


def _join_room(registry, room_id):
    """room_join policy (slide 6). -> room_id if a game with that id
    exists, else None -- unlike _create_room, joining never creates: a room
    is joined by its id, typed in by whoever created it and read out to
    whoever is joining, so a typo must be refused, not silently opened as a
    brand-new empty room under that name.

    Seating inside the room needs no new code at all once game_id is
    chosen here: GameRegistry.join already gives "w" to the first username,
    "b" to the second and "viewer" to everyone after, which is exactly what
    the slide describes for "inside a room" -- evidence the seam
    GameRegistry.create(game_id=...) provided was the right one."""
    if room_id not in registry.game_ids():
        return None
    return room_id


async def _handle_client(websocket, registry, clients, default_game, db_conn):  # pragma: no cover, pylint: disable=too-many-locals
    # One coroutine genuinely touches this many independent pieces of
    # state (the connection, three collaborators threaded in from _main,
    # and everything the login/room/command-loop steps compute along the
    # way) -- splitting it up would just move names around, the same
    # reasoning client.py's build_client/run give their own disables.
    """One coroutine per connection: read the login username/password the
    client sends first, join the policy-chosen game, send `assigned`
    before the first `state` so the client knows its role from the
    outset, register the connection, then apply every command it sends --
    checked against its seat by GameSession.submit -- until it
    disconnects, at which point it leaves the game (its seat stays held;
    see GameRegistry.leave).

    A wrong password (_authenticate) or a username already connected to
    the game it would join (GameRegistry.AlreadyConnectedError) both get
    refused outright -- an `error`, then close, before `clients` or
    GameRegistry.join is ever touched, so neither reaches the command loop
    or GameRegistry.leave below.

    Room (slide 6): the client's optional second message, right after
    login, is room_create or room_join (see _read_room_choice); when
    present it picks game_id via _create_room/_join_room instead of
    _find_or_create_game, and a chosen/created room is confirmed with
    `room` before anything else -- refused the same way if the name is
    already taken (create) or does not exist (join)."""
    username, password = await _read_login(websocket)
    if not _authenticate(db_conn, username, password):
        _log.warning("refused %s: bad password", username)
        await websocket.send(protocol.dumps(protocol.error("bad_password")))
        await websocket.close()
        return
    room_choice = await _read_room_choice(websocket)
    if room_choice is None:
        game_id = _find_or_create_game(registry, default_game)
    else:
        action, room_id = room_choice
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
            return
        await websocket.send(protocol.dumps(protocol.room(game_id)))
    try:
        color = registry.join(game_id, username)
    except AlreadyConnectedError:
        _log.warning("refused %s: already connected to game %s", username, game_id)
        await websocket.send(protocol.dumps(protocol.error("already_connected")))
        await websocket.close()
        return
    clients[websocket] = (game_id, username)
    _log.info("%s joined game %s as %s", username, game_id, color)
    try:
        await websocket.send(protocol.dumps(protocol.assigned(color)))
        await _send_state(websocket, registry.session(game_id))
        async for raw in websocket:
            try:
                message = protocol.loads(raw)
            except protocol.ProtocolError:
                _log.exception("dropping malformed frame from %s in game %s",
                                username, game_id)
                continue
            session = registry.session(game_id)
            if session is None:
                continue  # the game's linger period already elapsed
            applied = session.submit(message, registry.color_of(game_id, username))
            _log.info("%s %s from %s in game %s",
                       "applied" if applied else "refused", message.get("type"),
                       username, game_id)
    finally:
        clients.pop(websocket, None)
        registry.leave(game_id, username)
        _log.info("%s disconnected from game %s", username, game_id)


async def _tick_loop(registry, clients):  # pragma: no cover
    """Advance every game by a fixed step on a fixed interval, then push
    each game's own snapshot only to the clients sitting in that game.
    Today every client shares one game (see _find_or_create_game); once
    Room exists they will not, and broadcasting per-game already handles
    that -- Room needs no change here. A client whose send fails (it
    dropped the connection) is removed from `clients` rather than stopping
    the broadcast for everyone else.

    Also logs a summary every _SUMMARY_INTERVAL_MS (tick count, live games,
    connected clients) -- never the per-tick broadcast itself; see
    _SUMMARY_INTERVAL_MS's comment for why not."""
    tick_count = 0
    ms_since_summary = 0
    while True:
        await asyncio.sleep(_TICK_MS / 1000)
        registry.advance(_TICK_MS)
        tick_count += 1
        ms_since_summary += _TICK_MS
        if ms_since_summary >= _SUMMARY_INTERVAL_MS:
            ms_since_summary = 0
            # Known gap, seen live in this summary (live_games=0,
            # connected_clients=3): a client is never told its game was
            # removed after the linger period elapses (GameRegistry drops
            # it silently, see common/registry.py's GAME_END_LINGER_MS),
            # so `clients` can outlive every game_ids() entry it points
            # at. Those clients stay connected, attached to a game_id
            # registry.session() now returns None for, and see a frozen
            # board (the tick loop's per-game send below simply has
            # nothing to send them). Not fixed here -- noted because this
            # summary is what makes it visible at all.
            _log.info("tick=%d live_games=%d connected_clients=%d",
                       tick_count, len(registry.game_ids()), len(clients))
        dead = set()
        for game_id in registry.game_ids():
            session = registry.session(game_id)
            if session is None:
                continue
            message = protocol.dumps(protocol.state(session.snapshot()))
            for websocket, (client_game_id, _username) in clients.items():
                if client_game_id != game_id:
                    continue
                try:
                    await websocket.send(message)
                except websockets.ConnectionClosed:
                    dead.add(websocket)
        for websocket in dead:
            clients.pop(websocket, None)


def _connect_db():  # pragma: no cover
    """Connect to Postgres and make sure the players schema exists
    (including Step 8's pw_hash/salt columns). -> the connection, for the
    server to keep and reuse for the rest of its life -- login checks
    (_authenticate) and rating updates (_update_ratings_on_game_end) both
    need one. -> None on any failure, logged and swallowed rather than
    raised, so the caller starts the game server either way (Server_
    Design.md section 10: live games do not depend on the database) --
    every later user of this connection already treats None as "skip the
    check this needs a database for"."""
    try:
        conn = db.connect()
        db.ensure_schema(conn)
        _log.info("connected to Postgres and verified the players schema")
        return conn
    except Exception as exc:  # pylint: disable=broad-except
        # Deliberate: any failure here (unset DATABASE_URL, unreachable
        # host, auth failure) must not stop the game server from starting,
        # per the design doc's claim that live games do not depend on the
        # database -- expected and handled, not a crash, so a one-line
        # warning naming the reason is what belongs in the log, not
        # _log.exception's full traceback. Keep the traceback for
        # failures that are actually unexpected; this is not one.
        _log.warning("Postgres unavailable (%s); starting without it, "
                     "no accounts or ratings until it is reachable", exc)
        return None


def _update_ratings_on_game_end(db_conn, payload):
    """GAME_END subscriber (slide 4's rating half): reads `winner`/`seats`
    from the payload GameRegistry already publishes and writes new ELO
    ratings for the "w" and "b" seats. This is the only new subscriber
    Step 8 needed -- GameRegistry does not change, exactly as its own
    module docstring says the bus exists to make possible.

    Does nothing when `winner` is None (an uncounted game -- see
    common.elo.new_ratings' own docstring), when either seat is empty (a
    game that never had two players), or when `db_conn` is None (Postgres
    unreachable -- see _connect_db). Ignores "viewer" seats: `seats` may
    hold more than two usernames, only "w"/"b" affect rating.

    Never raises into the registry that published this event -- wrapped in
    a broad except, same reasoning as _authenticate's: a database failure
    here must not stop the tick loop that published GAME_END, only skip
    recording this one game's result (write-behind, per Server_Design.md).
    A missing player row (get_rating returns None -- possible if the
    database was unreachable at THAT player's login, see _authenticate)
    is treated the same way: logged and skipped, not a crash."""
    if db_conn is None:
        return
    winner = payload["winner"]
    if winner is None:
        return
    seats = payload["seats"]
    white_user = next((user for user, color in seats.items() if color == "w"), None)
    black_user = next((user for user, color in seats.items() if color == "b"), None)
    if white_user is None or black_user is None:
        return
    try:
        white_rating = db.get_rating(db_conn, white_user)
        black_rating = db.get_rating(db_conn, black_user)
        if white_rating is None or black_rating is None:
            _log.warning("skipping rating update for game %s: unknown player(s)",
                         payload["game_id"])
            return
        new_white, new_black = elo.new_ratings(white_rating, black_rating, winner)
        db.update_ratings(db_conn, white_user, black_user, new_white, new_black)
        _log.info("rating update: %s %d->%d, %s %d->%d",
                   white_user, white_rating, new_white,
                   black_user, black_rating, new_black)
    except Exception:  # pylint: disable=broad-except
        _log.exception("rating update failed for game %s", payload["game_id"])


async def _main():  # pragma: no cover
    _log.info("starting kung-fu chess server")
    db_conn = _connect_db()
    bus = Bus()
    # Nothing else subscribes to GAME_START yet -- publishing it
    # unconditionally from here on is what lets ELO (a later step) attach
    # as a bus subscriber, with no change to GameRegistry or this file.
    # GAME_END gets two subscribers here: one purely to log the winner
    # (this is the only place that knows how to turn a game_id into a log
    # line, so it belongs here rather than in GameRegistry, which does not
    # log), and _update_ratings_on_game_end (Step 8) -- the entire ELO
    # half of slide 4 is this one extra subscribe() call, exactly as
    # GameRegistry's own module docstring says the bus was built to allow.
    bus.subscribe(topics.GAME_END, lambda payload: _log.info(
        "game %s ended, winner=%s", payload["game_id"], payload["winner"]))
    bus.subscribe(topics.GAME_END,
                  lambda payload: _update_ratings_on_game_end(db_conn, payload))
    # king_type is passed explicitly rather than left at GameRegistry's own
    # default: both currently say "K", but that is one fact declared twice.
    # If _CONFIG's king token ever changed, an implicit default here would
    # silently desync -- the registry would keep detecting game_over
    # correctly (that comes from the engine) but _winner_of would find no
    # matching king and report winner=None forever.
    registry = GameRegistry(_build_session, bus=bus, king_type=_CONFIG.king_type)
    clients = {}  # websocket -> (game_id, username)
    default_game = {"id": None}  # see _find_or_create_game

    async def handler(websocket):
        await _handle_client(websocket, registry, clients, default_game, db_conn)

    async with websockets.serve(handler, _HOST, _PORT):
        _log.info("listening on ws://%s:%d", _HOST, _PORT)
        await _tick_loop(registry, clients)


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    # Console (above) is for watching a session live; the file (below) is
    # for looking at one afterward -- slide 6 wants both, and this is what
    # makes there be a file to look at. Shared with client.py, so the two
    # log files cannot drift into different formats.
    add_file_logging(_LOG_PATH)
    # Docker's HEALTHCHECK (see Dockerfile) opens a bare TCP socket to our
    # port every 10s and closes it again without ever sending a WebSocket
    # handshake -- websockets logs that as an ERROR with a full traceback,
    # on its own "websockets.server" logger, every single time. That is
    # our own healthcheck probing the port, not a real error, and at one
    # every 10s it would drown out everything slide 6 actually wants this
    # log for. Raising the level on that ONE logger -- not root, and not
    # our own __main__ logger below, which keeps logging at INFO exactly
    # as before -- is what silences just this noise and nothing else.
    logging.getLogger("websockets.server").setLevel(logging.CRITICAL)
    asyncio.run(_main())
