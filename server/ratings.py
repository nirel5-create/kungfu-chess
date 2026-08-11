"""The two places this server touches Postgres directly: connecting at
startup, and writing new ELO ratings when a game ends decisively.
"""

import logging

from common import db, elo

_log = logging.getLogger(__name__)


def _connect_db():  # pragma: no cover
    """Connect to Postgres and make sure the players schema exists
    (including the pw_hash/salt columns). -> the connection, for the
    server to keep and reuse for the rest of its life -- login checks
    (server.auth._authenticate) and rating updates
    (_update_ratings_on_game_end) both need one. -> None on any failure,
    logged and swallowed rather than raised, so the caller starts the
    game server either way (Server_Design.md section 10: live games do
    not depend on the database) -- every later user of this connection
    already treats None as "skip the check this needs a database for"."""
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
    """GAME_END subscriber (the rating half): reads `winner`/`seats` from
    the payload GameRegistry already publishes and writes new ELO ratings
    for the "w" and "b" seats. This is the only subscriber ratings
    needed -- GameRegistry does not change, exactly as its own module
    docstring says the bus exists to make possible.

    Does nothing when `winner` is None (an uncounted game -- see
    common.elo.new_ratings' own docstring), when either seat is empty (a
    game that never had two players), or when `db_conn` is None (Postgres
    unreachable -- see _connect_db). Ignores "viewer" seats: `seats` may
    hold more than two usernames, only "w"/"b" affect rating.

    Never raises into the registry that published this event -- wrapped in
    a broad except, same reasoning as server.auth._authenticate's: a
    database failure here must not stop the tick loop that published
    GAME_END, only skip recording this one game's result (write-behind,
    per Server_Design.md). A missing player row (get_rating returns None
    -- possible if the database was unreachable at THAT player's login,
    see server.auth._authenticate) is treated the same way: logged and
    skipped, not a crash.

    -> (white_user, new_white, black_user, new_black) on a successful
    update, so server.composition's own subscriber can hand both new ratings to
    the rating_updates list -- server.tick drains it every tick and
    pushes each still-connected player a fresh protocol.rating (mirroring
    ended_games' own hand-off list). -> None whenever no update was made,
    for any of the reasons above."""
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
