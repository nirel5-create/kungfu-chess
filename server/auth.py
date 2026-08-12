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
    """-> whether `username`/`password` may log in. A new username
    creates the account; an existing one must match its stored password.
    -> True when `db_conn` is None or the check itself raises: live games
    must not depend on Postgres, so an outage skips this check instead of
    locking every player out."""
    if db_conn is None:
        return True
    try:
        if db.create_player(db_conn, username, password):
            return True
        return db.verify_password(db_conn, username, password)
    except Exception as exc:  # pylint: disable=broad-except
        # Deliberate: a failure here (connection dropped mid-session,
        # Postgres restarting) is expected and handled, not a crash, so a
        # one-line warning naming the reason is what belongs in the log --
        # not _log.exception's full traceback, which would misrepresent a
        # handled condition as one and must not turn into a rejected login.
        _log.warning("password check failed for %s (%s); letting them in, "
                     "play continues without the database", username, exc)
        return True


def _reserve_username(connected_usernames, username):
    """Atomically check-and-reserve `username` server-wide -- one
    connection per account, checked before any room choice is read.
    -> True, reserving `username`, if it was free; -> False, unchanged, if
    not. The caller must remove `username` on disconnect, or a leak here
    locks that account out until the server restarts."""
    if username in connected_usernames:
        return False
    connected_usernames.add(username)
    return True


def _current_rating(db_conn, username):  # pragma: no cover
    """-> `username`'s current rating, falling back to db.DEFAULT_RATING
    (logged, never raised) when `db_conn` is None, `username` has no
    stored rating, or the lookup itself raises: a rating lookup failing
    must not block Play's pairing or the home dialog's display of it."""
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
