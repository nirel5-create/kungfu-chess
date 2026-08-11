"""Login: reading the client's first message, checking or creating the
account it names, and reserving the username for the life of the
connection.
"""

import logging

import websockets

from common import db, protocol

_log = logging.getLogger(__name__)


async def _read_login(websocket):  # pragma: no cover
    """The (username, password) from the client's first message (a
    `login`), or ("?", "") if the connection closes or sends something
    else before logging in. A missing/malformed login never blocks a seat
    from being assigned -- there being no account to check a password
    against is treated the same as a real "?" account always was."""
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
    username creates the account at common.db.DEFAULT_RATING (first time,
    whatever password is written becomes the password); an existing one
    must match what create_player already refused to overwrite.

    -> True unconditionally when `db_conn` is None (Postgres unreachable
    at startup, see server.ratings.connect_db) or when the check itself
    raises (unreachable mid-session) -- Server_Design.md promises live
    games do not depend on Postgres, and this is where that promise is
    either kept or broken: a database outage must not lock every player
    out, only skip the one check it cannot perform."""
    if db_conn is None:
        return True
    try:
        if db.create_player(db_conn, username, password):
            return True
        return db.verify_password(db_conn, username, password)
    except Exception as exc:  # pylint: disable=broad-except
        # Deliberate, same reasoning as server.ratings.connect_db's own
        # broad except: any failure here (connection dropped mid-session,
        # Postgres restarting) must not turn into a rejected login --
        # expected and handled, not a crash, which is exactly why this is
        # a one-line warning naming the reason rather than _log.exception's
        # full traceback: a stack trace here would misrepresent a handled
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
    dialog that could never succeed. This runs before a room choice is
    ever read (see server.connection._handle_client), so that never
    happens now.

    The caller is responsible for removing `username` again on disconnect
    -- including an abnormal one -- or a leak here locks that player out
    of their own account until the server restarts; see
    server.connection._handle_client's own try/finally for where that
    happens."""
    if username in connected_usernames:
        return False
    connected_usernames.add(username)
    return True


def _current_rating(db_conn, username):  # pragma: no cover
    """-> `username`'s current rating -- for Play's pairing window and for
    the home dialog's own display of it (protocol.rating). Falls back to
    db.DEFAULT_RATING -- logged, never raised -- when `db_conn` is None
    (Postgres unreachable at startup), `username` has no stored rating
    (should not normally happen: login already creates or looks up the
    account first, see _authenticate), or the lookup itself raises
    (Postgres unreachable mid-session). Neither caller may stop working
    just because a rating lookup did, the same promise every other
    database-touching path in this server keeps (see _authenticate,
    server.ratings.update_ratings_on_game_end)."""
    if db_conn is not None:
        try:
            rating = db.get_rating(db_conn, username)
        except Exception as exc:  # pylint: disable=broad-except
            _log.warning("rating lookup failed for %s (%s); using default %d",
                         username, exc, db.DEFAULT_RATING)
            return db.DEFAULT_RATING
        if rating is not None:
            return rating
        _log.warning("no stored rating for %s; using default %d", username, db.DEFAULT_RATING)
    return db.DEFAULT_RATING
