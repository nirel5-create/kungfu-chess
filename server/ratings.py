"""The two places this server touches Postgres directly: connecting at
startup, and writing new ELO ratings when a game ends decisively.
"""

import logging

from common import db, elo

_log = logging.getLogger(__name__)


def _connect_db():  # pragma: no cover
    """Connect to Postgres and make sure the players schema exists.
    -> the connection, for the server to keep and reuse for its whole
    life. -> None on any failure, logged and swallowed rather than
    raised: live games must not depend on the database, so the server
    starts either way."""
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
    """GAME_END subscriber: writes new ELO ratings for the "w"/"b" seats,
    skipping an uncounted game, a missing seat, or an unreachable database
    (logged, not raised) -- a failure here must only skip that game's
    result, never break the tick loop that published it. -> (white_user,
    new_white, black_user, new_black) on success, else None."""
    if db_conn is None:
        return None
    winner = payload["winner"]
    if winner is None:
        return None
    seats = payload["seats"]
    white_user = next((user for user, color in seats.items() if color == "w"), None)
    black_user = next((user for user, color in seats.items() if color == "b"), None)
    if white_user is None or black_user is None:
        return None
    try:
        white_rating = db.get_rating(db_conn, white_user)
        black_rating = db.get_rating(db_conn, black_user)
        if white_rating is None or black_rating is None:
            _log.warning("skipping rating update for game %s: unknown player(s)",
                         payload["game_id"])
            return None
        new_white, new_black = elo.new_ratings(white_rating, black_rating, winner)
        db.update_ratings(db_conn, white_user, black_user, new_white, new_black)
        _log.info("rating update: %s %d->%d, %s %d->%d",
                   white_user, white_rating, new_white,
                   black_user, black_rating, new_black)
        return white_user, new_white, black_user, new_black
    except Exception:  # pylint: disable=broad-except
        _log.exception("rating update failed for game %s", payload["game_id"])
        return None
