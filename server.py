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
separate policy function that decides which game a new connection joins when
it asks for neither a room nor Play -- everyone left over shares one open
game, creating a fresh one when none is open.

Room (slide 6) replaced only that one function's default: room_create/
room_join pick game_id via _create_room/_join_room instead. Play (slide 5.1,
Step 10) is a third, separate path, not a fourth policy for
_find_or_create_game to choose between: a Play seeker has no game_id at all
until common.matchmaker.MatchMaker pairs it with someone, which can take up
to a minute, so it waits (_play_matchmaking) instead of being handed a game
immediately -- see _tick_loop for where the actual pairing happens.
GameRegistry itself needed no change for any of the three.

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

Step 10 (slide 5.1) adds Play: common.matchmaker.MatchMaker is a pure queue
(no sockets, no database, no wall clock -- see its own module docstring)
that this file feeds ratings into and reads pairs/timeouts out of, once per
tick, the same explicit-time discipline GameRegistry.advance already keeps.
This file is what turns a pairing into an actual game (GameRegistry.create
plus two joins) and a timeout into a message, and what looks up a rating in
the first place (common.db.get_rating) -- none of that is MatchMaker's job.

Step 11 fixes four things players could not see or do. Two are refusals
moved earlier or added outright: a duplicate username is now refused at
login (_reserve_username), before the Room dialog, not after; an
undisplayable username or room name (common.validation.is_displayable) is
refused before it ever reaches the score panel or room indicator as boxes
or garbage. The other two give every client the server's own view of
history: this file now runs its own common.capture_log.CaptureLog per
game -- a server-side clone of view.observer.GameObserver's pure capture-
detection algorithm, not an import of it (view/ is the client's OpenCV
rendering stack, deliberately not part of the server's Docker image; see
CaptureLog's own module docstring for the ModuleNotFoundError this fixes)
-- fed the same snapshots the tick loop already produces, and sends the
current log, scores and real display names (_send_history) whenever they
change, and once, immediately, whenever a connection joins or reconnects
(_run_game_loop) -- so a client that missed the start of the game,
including a viewer who joined mid-game, sees the exact same history every
other client does, computed once, here, rather than piecing together its
own from whatever it happened to see. Real names replace "Player 1"/
"Player 2" computed fresh from GameRegistry.seats every time
(_seat_names), not from anything on CaptureLog -- it has no concept of
names at all, only captures and score, precisely because a name can
change (a seat gets taken) after a game already has one.

Run with:  python server.py
"""
# pylint: disable=too-many-lines
# Four steps (5, 8, 9, 10, 11) of plumbing for one connection lifecycle
# and one tick loop, each already broken into its own small function with
# a clear single job -- the line count is many small, cohesive pieces
# accumulated over real feature growth, not one function or one
# responsibility that has grown unwieldy. Splitting the module itself
# (e.g. matchmaking vs. room/default-game policy vs. the tick loop) is a
# reasonable future cleanup, but is not part of implementing any single
# step, so it is not done here.

import asyncio
import logging

import websockets

from common import db, elo, net, protocol, topics
from common.bus import Bus
from common.capture_log import CaptureLog
from common.logsetup import add_file_logging
from common.matchmaker import MatchMaker
from common.registry import AlreadyConnectedError, GameRegistry
from common.validation import is_displayable
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


def _reserve_username(connected_usernames, username):
    """Atomically check-and-reserve `username` server-wide: one connection
    per account, regardless of which game or room it ends up in -- a
    username is one person. -> True, and adds `username` to
    `connected_usernames`, if it was free. -> False, leaving
    `connected_usernames` untouched, if it was already there.

    Refusing here, at login, is what fixes a bug found in manual testing:
    the equivalent check inside GameRegistry.join (kept, unchanged, as a
    second correct guard at the per-game layer) only runs after the
    client's room choice is known, so a duplicate login used to be shown
    the whole Room dialog before being refused -- wasted effort on a
    dialog that could never succeed. This runs before _read_room_choice
    is ever called (see _handle_client), so that never happens now.

    The caller is responsible for removing `username` again on disconnect
    -- including an abnormal one -- or a leak here locks that player out
    of their own account until the server restarts; see _handle_client's
    own try/finally for where that happens."""
    if username in connected_usernames:
        return False
    connected_usernames.add(username)
    return True


def _rating_for_matchmaking(db_conn, username):  # pragma: no cover
    """-> `username`'s rating, for Play's pairing window (slide 5.1).
    Falls back to db.DEFAULT_RATING -- logged, never raised -- when
    `db_conn` is None (Postgres unreachable at startup), `username` has no
    stored rating (should not normally happen: login already creates or
    looks up the account first, see _authenticate), or the lookup itself
    raises (Postgres unreachable mid-session). Play must not stop working
    just because a rating lookup did, the same promise every other
    database-touching path in this file keeps (see _authenticate,
    _update_ratings_on_game_end)."""
    if db_conn is not None:
        try:
            rating = db.get_rating(db_conn, username)
        except Exception as exc:  # pylint: disable=broad-except
            _log.warning("rating lookup failed for %s (%s); using default %d for matchmaking",
                         username, exc, db.DEFAULT_RATING)
            return db.DEFAULT_RATING
        if rating is not None:
            return rating
        _log.warning("no stored rating for %s; using default %d for matchmaking",
                     username, db.DEFAULT_RATING)
    return db.DEFAULT_RATING


async def _read_room_choice(websocket):  # pragma: no cover
    """-> (protocol.ROOM_CREATE, name), (protocol.ROOM_JOIN, room_id), or
    (protocol.PLAY, None) if the client's optional second message (right
    after login) is one of those three types within
    _ROOM_MESSAGE_TIMEOUT_S, else None. None covers two cases identically:
    a client that never implements the dialog and sends nothing at all,
    and a client that sent something this function does not recognize --
    both fall back to _find_or_create_game exactly as before Room existed,
    per STEP7_ROOMS.md. A malformed frame is treated the same way rather
    than as an error: at this point in the handshake the client has
    nothing else legitimate to send beyond these three, so this is
    defence in depth, the same spirit as GameSession.submit silently
    ignoring an unrecognized message type.

    protocol.PLAY is its own outcome, not folded into None any more
    (Step 10): _handle_client sends it to matchmaking instead of the
    shared game -- see _play_matchmaking."""
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


async def _play_matchmaking(websocket, matchmaker, matchmaking,
                             db_conn, username):  # pragma: no cover
    """Enqueue `username` in `matchmaker` (Play, slide 5.1) and wait for
    _tick_loop to either pair them or time them out.

    -> (game_id, color) once _tick_loop has paired and joined this
    connection -- it has also already sent matchmaking("found") and
    assigned(color) by then, see _seat_matched_pair -- or None once timed
    out (matchmaking("timeout") already sent, see
    _report_matchmaking_timeout) or once this connection's own socket
    closes while still queued.

    `matchmaking` is a {username: (websocket, future, rating)} box
    threaded from _main, the same shape `clients` has for joined
    connections: _tick_loop needs a way to reach a WAITING connection's
    own websocket (nothing else has it -- there is no game_id yet), and
    needs `future` to hand the outcome back to this coroutine and
    `rating` to log a pairing or timeout without asking the database
    again.

    A disconnect while queued is detected by racing `future` (resolved by
    _tick_loop) against websocket.wait_closed(): otherwise nothing here is
    reading the socket, so a closed connection would go unnoticed until it
    eventually timed out on its own, up to a minute later -- during which
    _tick_loop could still pair it with a live opponent, who would then be
    waiting on someone already gone. That is the same class of bug Step 9
    fixed for the abandoned default game, and exactly what this step's own
    design doc warns against repeating."""
    rating = _rating_for_matchmaking(db_conn, username)
    future = asyncio.get_running_loop().create_future()
    matchmaking[username] = (websocket, future, rating)
    matchmaker.enqueue(username, rating)
    _log.info("%s entered matchmaking at rating %d", username, rating)
    try:
        await websocket.send(protocol.dumps(protocol.matchmaking("searching")))
        closed = asyncio.ensure_future(websocket.wait_closed())
        try:
            await asyncio.wait({future, closed}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            closed.cancel()
        return future.result() if future.done() else None
    except websockets.ConnectionClosed:
        return None
    finally:
        matchmaker.cancel(username)
        matchmaking.pop(username, None)


def _observer_for(observers, game_id):  # pragma: no cover
    """-> the CaptureLog for `game_id`, creating one the first time it is
    asked for. Shared by _run_game_loop (an immediate send when a
    connection joins or reconnects) and _tick_loop (the ongoing
    send-on-change broadcast), so whichever runs first for a given
    game_id is the one that actually creates it; the other just reuses
    it."""
    observer = observers.get(game_id)
    if observer is None:
        observer = CaptureLog(_CONFIG)
        observers[game_id] = observer
    return observer


def _seat_names(seats):  # pragma: no cover
    """-> (white_name, black_name): the CURRENT username seated at each
    color, or "Player 1"/"Player 2" for a seat nobody has taken yet.

    Computed fresh from `seats` (GameRegistry.seats(game_id)) every time:
    CaptureLog (see its own module docstring) has no concept of names at
    all, precisely because a name can change -- a seat gets taken --
    after a game already has one, and a game can easily already have a
    CaptureLog (created on its very first tick, before anyone has joined)
    by the time its second seat is taken. This is what lets a placeholder
    become a real name the moment that seat is taken (Step 11)."""
    white = next((user for user, color in seats.items() if color == "w"), None)
    black = next((user for user, color in seats.items() if color == "b"), None)
    return white or "Player 1", black or "Player 2"


async def _send_history(websocket, observers, registry, game_id):  # pragma: no cover
    """Send `game_id`'s current move log, scores and names to `websocket`
    -- used for an immediate send when a connection joins or reconnects
    (_run_game_loop), so it is never left showing an empty panel just
    because it was not there for the captures that already happened
    (Step 11) -- a viewer joining mid-game gets this too, for the same
    reason and at no extra cost. _tick_loop's own send-on-change
    broadcast builds the same message itself, for potentially many
    recipients at once, rather than calling this once per recipient."""
    observer = _observer_for(observers, game_id)
    white_name, black_name = _seat_names(registry.seats(game_id))
    message = protocol.dumps(protocol.history(
        white_name, black_name, observer.score_of("w"), observer.score_of("b"), observer.log()))
    await websocket.send(message)


async def _run_game_loop(websocket, registry, clients, game_id,
                          color, username, observers):  # pragma: no cover
    # pylint: disable=too-many-arguments, too-many-positional-arguments
    # Seven independent pieces of context every caller already has in
    # hand (the connection, the three collaborators from _main, and the
    # seat this particular connection just got, however it got it) --
    # the same reasoning every other disable in this file gives.
    """Register the connection in `clients`, send the current state and
    history, then read and apply commands until it disconnects -- shared
    by every path that ends with a seat in a game (the shared default
    game, a room, or a Play match), so there is exactly one place that
    runs the command loop and exactly one place that cleans up after it.

    Does NOT send `assigned`: the shared/room paths send it themselves
    right before calling this; a Play match already had it sent by
    _tick_loop's _seat_matched_pair, before this connection's own
    coroutine even learns which game or color it was matched to."""
    clients[websocket] = (game_id, username)
    _log.info("%s joined game %s as %s", username, game_id, color)
    try:
        await _send_state(websocket, registry.session(game_id))
        await _send_history(websocket, observers, registry, game_id)
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
        if color in ("w", "b"):
            # A viewer leaving starts no countdown at all (see
            # GameRegistry.leave), so nothing to log for that case --
            # `color` is exactly the seat check that already distinguishes
            # them, already known by the caller, no extra registry query
            # needed.
            _log.info("countdown started for %s in game %s", username, game_id)


def _find_or_create_game(registry, default_game, username):
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

    "Open" means the game exists, is not yet game_over, AND has at least
    one currently-connected player -- UNLESS `username` already holds a
    seat in it, in which case it is "open" regardless. That exception is
    what preserves reconnecting to the default game (a disconnected
    player's seat is kept, per GameRegistry.join, precisely so they can
    come back to it -- Step 9's countdown gives that window a deadline
    but does not remove the seat before it), which already works and must
    keep working. Without the exception, a game everyone had actually
    left is skipped (a bug found by manual testing: a stranger arriving
    at the default game used to be handed one still holding a seated but
    long-gone player, and sat there waiting for an opponent who was never
    coming back) -- a finished game is skipped the same way it always was
    (the original bug fix this function has always made -- a new arrival
    never gets handed a permanently-ended game), which is also why the
    remembered id must be re-checked every call rather than trusted
    forever."""
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


async def _join_or_refuse(websocket, registry, game_id, username):  # pragma: no cover
    """registry.join(game_id, username), or -- on AlreadyConnectedError --
    send `error`, close `websocket`, and return None. -> the assigned
    color on success. Shared by every path in _handle_client that ends
    with a direct registry.join call, so the refuse-and-close sequence is
    written once. In practice this exception should not fire any more
    (the server-wide _reserve_username check already refuses a duplicate
    login before this is ever reached), but GameRegistry's own per-game
    check is kept regardless -- see _handle_client's own docstring -- so
    this still handles it correctly if it ever does."""
    try:
        return registry.join(game_id, username)
    except AlreadyConnectedError:
        _log.warning("refused %s: already connected to game %s", username, game_id)
        await websocket.send(protocol.dumps(protocol.error("already_connected")))
        await websocket.close()
        return None


async def _handle_client(websocket, registry, clients, default_game, db_conn,
                          matchmaker, matchmaking, connected_usernames,
                          observers):  # pragma: no cover
                          # pylint: disable=too-many-locals, too-many-arguments
                          # pylint: disable=too-many-positional-arguments
                          # pylint: disable=too-many-return-statements, too-many-branches
                          # pylint: disable=too-many-statements
    # One coroutine genuinely touches this many independent pieces of
    # state (the connection, seven collaborators threaded in from _main,
    # and everything the login/room/play/command-loop steps compute along
    # the way) -- splitting it up would just move names around, the same
    # reasoning client.py's build_client/run give their own disables.
    """One coroutine per connection: read the login username/password the
    client sends first, get a seat one of three ways (see below), then
    hand off to _run_game_loop, which registers the connection, sends the
    current state, and applies every command it sends -- checked against
    its seat by GameSession.submit -- until it disconnects.

    Four things refuse a connection outright -- an `error`, then close,
    before `clients` or GameRegistry.join is ever touched: an
    undisplayable username (Step 11, is_displayable -- checked first, so
    a name cv2 cannot even draw never reaches a password check or the
    database), a wrong password (_authenticate), a username already
    connected ANYWHERE on this server (_reserve_username -- checked next,
    before _read_room_choice is ever called, so a duplicate login never
    even sees the Room dialog), or one already connected to the specific
    game it would join (GameRegistry.AlreadyConnectedError -- a second,
    still-correct guard at the per-game layer, now normally unreachable
    since the server-wide check above already covers it).

    Once reserved, `username` is released in the outer `finally` no
    matter how this coroutine ends -- normal disconnect, refusal further
    down (room_exists, invalid_room_name, ...), or an unexpected
    exception -- so a player is never locked out of their own account by
    a connection that ended abnormally.

    Three ways to get a seat, from the client's optional second message
    right after login (see _read_room_choice):
    - Play (slide 5.1): GameRegistry.game_of(username) first, in case this
      is a reconnect -- a player whose disconnect countdown (Step 9) is
      still running, or who simply still holds a seat, must return to
      that seat, not be queued to search for a new opponent while their
      own held seat sits there waiting for them (Step 12). Only once
      game_of finds nothing does this fall through to matchmaking:
      _play_matchmaking enqueues this connection and waits for _tick_loop
      to pair or time it out; a timeout closes the connection with no
      game ever entered.
    - Room (slide 6): room_create or room_join picks game_id via
      _create_room/_join_room instead of _find_or_create_game, and a
      chosen/created room is confirmed with `room` before anything else --
      refused the same way if the name is undisplayable (Step 11), already
      taken (create), or does not exist (join). Room names a specific
      game, so it has no equivalent reconnect check of its own to make --
      joining the same room again already lands back on the same seat via
      the ordinary GameRegistry.join path below.
    - Neither: the ordinary shared game (_find_or_create_game), exactly
      as before Room or Play existed -- it already has its own equivalent
      reconnect exception, for the one default game it remembers."""
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
        room_choice = await _read_room_choice(websocket)
        if room_choice is not None and room_choice[0] == protocol.PLAY:
            held_game_id = registry.game_of(username)
            if held_game_id is not None:
                color = await _join_or_refuse(websocket, registry, held_game_id, username)
                if color is None:
                    return
                await websocket.send(protocol.dumps(protocol.assigned(color)))
                await _run_game_loop(websocket, registry, clients, held_game_id, color,
                                      username, observers)
                return
            matched = await _play_matchmaking(websocket, matchmaker, matchmaking, db_conn, username)
            if matched is None:
                await websocket.close()
                return
            game_id, color = matched
            await _run_game_loop(websocket, registry, clients, game_id, color, username, observers)
            return
        if room_choice is None:
            game_id = _find_or_create_game(registry, default_game, username)
        else:
            action, room_id = room_choice
            if not is_displayable(room_id):
                _log.warning("refused %s: undisplayable room name %r", username, room_id)
                await websocket.send(protocol.dumps(protocol.error("invalid_room_name")))
                await websocket.close()
                return
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
        color = await _join_or_refuse(websocket, registry, game_id, username)
        if color is None:
            return
        await websocket.send(protocol.dumps(protocol.assigned(color)))
        await _run_game_loop(websocket, registry, clients, game_id, color, username, observers)
    finally:
        connected_usernames.discard(username)


async def _seat_matched_pair(registry, clients, matchmaking, user_a, user_b):  # pragma: no cover
    """Create a fresh game for `user_a`/`user_b` (a Play match, slide
    5.1), join both, and tell each matchmaking("found") then
    assigned(color), in that order -- protocol.matchmaking's own
    docstring promises `found` is followed by `assigned`.

    `matchmaking[username]` is always present here: matchmaker.advance()
    can only return a username that was still in ITS OWN queue at that
    exact moment, and _play_matchmaking -- the only thing that ever
    removes a username from either the matchmaker or `matchmaking` --
    always removes both together, synchronously, with no `await` between
    the two removals.

    A player whose socket already died while queued (a narrow race with
    _play_matchmaking's own disconnect detection -- see its docstring) is
    still seated here, since GameRegistry has no way to know otherwise,
    but is immediately left again the moment its found/assigned send
    fails: this hands the surviving opponent straight into the ordinary
    disconnect countdown (Step 9) instead of leaving it waiting on a
    partner who was never really there -- the same fix Step 9 already
    made for the abandoned-default-game case."""
    game_id = registry.create()
    for username in (user_a, user_b):
        websocket, future, rating = matchmaking[username]
        color = registry.join(game_id, username)
        try:
            await websocket.send(protocol.dumps(protocol.matchmaking("found")))
            await websocket.send(protocol.dumps(protocol.assigned(color)))
        except websockets.ConnectionClosed:
            registry.leave(game_id, username)
            future.set_result(None)
        else:
            clients[websocket] = (game_id, username)
            future.set_result((game_id, color))
        _log.info("matched %s (rating %d) into game %s as %s",
                   username, rating, game_id, color)


async def _report_matchmaking_timeout(matchmaking, username):  # pragma: no cover
    """Tell a timed-out seeker (slide 5: "pops up a message that can't
    find") and release their _play_matchmaking coroutine. `matchmaking
    [username]` is always present here -- see _seat_matched_pair's own
    docstring for why."""
    websocket, future, rating = matchmaking[username]
    try:
        await websocket.send(protocol.dumps(protocol.matchmaking("timeout")))
    except websockets.ConnectionClosed:
        pass
    future.set_result(None)
    _log.info("%s (rating %d) timed out waiting for a match", username, rating)


def _winner_username(seats, winner):
    """-> the username sitting in the `winner` seat, or None if there is no
    winner (a game with no result reports no name, not a color -- see
    protocol.game_over's own docstring) or, defensively, if the winning
    color was somehow never seated -- should not happen, since `winner` can
    only ever be a color GameRegistry itself found seated."""
    if winner is None:
        return None
    return next((user for user, color in seats.items() if color == winner), None)


async def _tick_loop(registry, clients, ended_games, matchmaker, matchmaking,
                      observers):  # pragma: no cover
                      # pylint: disable=too-many-locals, too-many-branches
                      # pylint: disable=too-many-statements, too-many-arguments
                      # pylint: disable=too-many-positional-arguments
    # A tick genuinely touches this many independent pieces (the summary
    # counters, the per-game client list reused for four different
    # broadcasts, the countdown bookkeeping, matchmaking, the per-game
    # observers) -- splitting it up would just move names around, the
    # same reasoning other disables in this file give. Four
    # send-if-appropriate blocks (state, game_over, history, countdown)
    # inside the same per-game loop, plus the pairing/timeout handling,
    # is what pushes the branch and statement counts over pylint's
    # default threshold -- each block is a few lines and reads linearly,
    # so splitting them into separate functions would trade one readable
    # loop for several that all need the same game_clients list (or
    # matchmaking/observers box) threaded through them.
    """Advance every game by a fixed step on a fixed interval, then push
    each game's own snapshot only to the clients sitting in that game.
    Today every client shares one game (see _find_or_create_game); once
    Room exists they will not, and broadcasting per-game already handles
    that -- Room needs no change here. A client whose send fails (it
    dropped the connection) is removed from `clients` rather than stopping
    the broadcast for everyone else.

    Also broadcasts the disconnect countdown (slide 5.2): for every game
    with an away player (GameRegistry.countdown_ms), send protocol.
    countdown(seconds) -- whole seconds, not milliseconds, and only when
    the second actually changes for that (game, username) pair, the same
    "send on change, not on every tick" reasoning _SUMMARY_INTERVAL_MS
    already uses. `last_countdown_seconds` remembers what was last sent
    per (game_id, username) and is rebuilt from scratch every tick, which
    is what makes a countdown that stops (the player reconnected, or the
    game ended) simply stop appearing in it -- nothing to explicitly
    clean up.

    Also broadcasts the outcome once a game ends: `ended_games` is a plain
    list a GAME_END bus subscriber appends its payload to (see _main) --
    GameRegistry.advance publishes GAME_END synchronously, from inside the
    registry.advance(...) call below, so by the time this function reaches
    the per-game loop every game that just ended this tick is already in
    it. A game that ended stays in registry.game_ids() for its whole
    GAME_END_LINGER_MS afterward (common/registry.py), which is many ticks
    at _TICK_MS=30 -- comfortably longer than the one tick `ended_games`
    is ever allowed to hold an entry for (drained, in full, every tick
    below), so an ended game's id is always still there to match against.
    Sent once per game, to whichever clients are connected to it at that
    moment -- the same clients its final `state` broadcast just went to.

    Also runs Play's matchmaking (slide 5.1): matchmaker.advance(_TICK_MS)
    once per tick, exactly like registry.advance -- time stays explicit
    here too, per this step's own design doc. Every pair gets a fresh game
    (_seat_matched_pair); every timeout gets told (_report_matchmaking_
    timeout). Both also resolve that connection's own _play_matchmaking
    future, which is the actual hand-off back to _handle_client's waiting
    coroutine -- Bus-style pub/sub was not used here because there is
    exactly one interested party per outcome (the seeker's own connection),
    not an open set of subscribers.

    Also runs each game's own CaptureLog (Step 11) and broadcasts its
    current log/scores/names whenever they change: `observer.observe` runs
    every tick, unconditionally, same as the observer's own docstring
    expects ("called as often or as rarely as the view likes"), but the
    actual `history` message is only sent when `(log length, white_name,
    black_name)` differs from `last_history_sent[game_id]` -- log length
    alone is enough to also cover score, since a score only ever changes
    together with a new log entry. `observers`/`last_history_sent` are
    pruned for any game_id no longer in registry.game_ids() at the end of
    each tick, so a finished-and-removed game's observer is not kept
    forever.

    Also logs a summary every _SUMMARY_INTERVAL_MS (tick count, live games,
    connected clients) -- never the per-tick broadcast itself; see
    _SUMMARY_INTERVAL_MS's comment for why not."""
    tick_count = 0
    ms_since_summary = 0
    last_countdown_seconds = {}  # (game_id, username) -> last-sent whole seconds
    last_history_sent = {}  # game_id -> (log length, white_name, black_name)
    while True:
        await asyncio.sleep(_TICK_MS / 1000)
        registry.advance(_TICK_MS)
        pairs, timed_out = matchmaker.advance(_TICK_MS)
        for user_a, user_b in pairs:
            await _seat_matched_pair(registry, clients, matchmaking, user_a, user_b)
        for username in timed_out:
            await _report_matchmaking_timeout(matchmaking, username)
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
        current_countdown_seconds = {}
        ended_by_game_id = {payload["game_id"]: payload for payload in ended_games}
        ended_games.clear()
        for game_id in registry.game_ids():
            session = registry.session(game_id)
            if session is None:
                continue
            game_clients = [websocket for websocket, (client_game_id, _username)
                             in clients.items() if client_game_id == game_id]
            message = protocol.dumps(protocol.state(session.snapshot()))
            for websocket in game_clients:
                try:
                    await websocket.send(message)
                except websockets.ConnectionClosed:
                    dead.add(websocket)
            ended_payload = ended_by_game_id.get(game_id)
            if ended_payload is not None:
                winner = ended_payload["winner"]
                winner_username = _winner_username(ended_payload["seats"], winner)
                game_over_message = protocol.dumps(protocol.game_over(winner, winner_username))
                for websocket in game_clients:
                    try:
                        await websocket.send(game_over_message)
                    except websockets.ConnectionClosed:
                        dead.add(websocket)
            observer = _observer_for(observers, game_id)
            observer.observe(session.snapshot(), tick_count * _TICK_MS)
            white_name, black_name = _seat_names(registry.seats(game_id))
            history_key = (len(observer.log()), white_name, black_name)
            if last_history_sent.get(game_id) != history_key:
                last_history_sent[game_id] = history_key
                history_message = protocol.dumps(protocol.history(
                    white_name, black_name,
                    observer.score_of("w"), observer.score_of("b"), observer.log()))
                for websocket in game_clients:
                    try:
                        await websocket.send(history_message)
                    except websockets.ConnectionClosed:
                        dead.add(websocket)
            for username, ms_left in registry.countdown_ms(game_id).items():
                seconds = -(-ms_left // 1000)  # ceiling: show 20..1, never a 0 flash
                key = (game_id, username)
                current_countdown_seconds[key] = seconds
                if last_countdown_seconds.get(key) == seconds:
                    continue
                countdown_message = protocol.dumps(protocol.countdown(seconds))
                for websocket in game_clients:
                    try:
                        await websocket.send(countdown_message)
                    except websockets.ConnectionClosed:
                        dead.add(websocket)
        last_countdown_seconds = current_countdown_seconds
        live_game_ids = set(registry.game_ids())
        for stale_id in set(observers) - live_game_ids:
            del observers[stale_id]
            last_history_sent.pop(stale_id, None)
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
    # GAME_END gets three subscribers here: one purely to log the winner
    # (this is the only place that knows how to turn a game_id into a log
    # line, so it belongs here rather than in GameRegistry, which does not
    # log), _update_ratings_on_game_end (Step 8) -- the entire ELO half of
    # slide 4 is this one extra subscribe() call, exactly as GameRegistry's
    # own module docstring says the bus was built to allow -- and
    # ended_games.append, which hands each payload to _tick_loop so it can
    # broadcast the outcome to that game's clients (Bus.publish is
    # synchronous, so a subscriber cannot itself await a websocket.send;
    # see _tick_loop's own docstring for why this hand-off is a plain list
    # rather than an async mechanism).
    bus.subscribe(topics.GAME_END, lambda payload: _log.info(
        "game %s ended, winner=%s", payload["game_id"], payload["winner"]))
    bus.subscribe(topics.GAME_END,
                  lambda payload: _update_ratings_on_game_end(db_conn, payload))
    ended_games = []  # GAME_END payloads awaiting _tick_loop's next broadcast
    bus.subscribe(topics.GAME_END, ended_games.append)
    # king_type is passed explicitly rather than left at GameRegistry's own
    # default: both currently say "K", but that is one fact declared twice.
    # If _CONFIG's king token ever changed, an implicit default here would
    # silently desync -- the registry would keep detecting game_over
    # correctly (that comes from the engine) but _winner_of would find no
    # matching king and report winner=None forever.
    registry = GameRegistry(_build_session, bus=bus, king_type=_CONFIG.king_type)
    clients = {}  # websocket -> (game_id, username)
    default_game = {"id": None}  # see _find_or_create_game
    matchmaker = MatchMaker()  # slide 5.1 -- see _play_matchmaking
    matchmaking = {}  # username -> (websocket, future, rating); see _play_matchmaking
    connected_usernames = set()  # Step 11 -- see _reserve_username
    observers = {}  # game_id -> CaptureLog; Step 11 -- see _observer_for

    async def handler(websocket):
        await _handle_client(websocket, registry, clients, default_game, db_conn,
                              matchmaker, matchmaking, connected_usernames, observers)

    async with websockets.serve(handler, _HOST, _PORT):
        _log.info("listening on ws://%s:%d", _HOST, _PORT)
        await _tick_loop(registry, clients, ended_games, matchmaker, matchmaking, observers)


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
