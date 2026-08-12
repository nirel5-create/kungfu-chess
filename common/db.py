"""Postgres connection and schema for player accounts and ratings.

An account is a username with a password (hashed, never stored in the
clear) and a rating that moves by ELO after every decisive game.

What this module owns: opening a connection from DATABASE_URL, creating and
upgrading the players schema, hashing/verifying passwords, and reading/
writing ratings.
What it does NOT own: the ELO arithmetic itself (common/elo.py), deciding
WHEN a rating changes (server.py's GAME_END subscriber), or sessions.
"""

import hashlib
import hmac
import os
import secrets

import psycopg

DEFAULT_RATING = 1200

# OWASP's Password Storage Cheat Sheet's long-standing baseline for
# PBKDF2-HMAC-SHA256 (their current guidance goes higher still, but that
# turns every login -- and every test that exercises one -- into a
# noticeably slow call; this is still a real, deliberately-chosen cost,
# not a placeholder). hashlib's implementation is C, so this is tens of
# milliseconds, not seconds.
_PBKDF2_ITERATIONS = 100_000
_SALT_BYTES = 16

# One statement, not two DDL calls: CREATE TABLE IF NOT EXISTS on its own
# only handles a database that has never seen this table before. An older
# deployment's players table can already exist without pw_hash/salt, so
# this statement must ALSO add those columns to a table that is already
# there -- ALTER TABLE ... ADD COLUMN IF NOT EXISTS is what makes that
# idempotent (safe to run again on a database that already has them).
_ENSURE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS players (
    username TEXT PRIMARY KEY,
    rating INTEGER NOT NULL DEFAULT 1200
);
ALTER TABLE players ADD COLUMN IF NOT EXISTS pw_hash BYTEA;
ALTER TABLE players ADD COLUMN IF NOT EXISTS salt BYTEA;
"""

_GET_RATING_SQL = "SELECT rating FROM players WHERE username = %s"

# A single atomic statement, not a SELECT followed by an INSERT: two
# connections doing SELECT-then-INSERT can both decide the row is missing
# and both try to insert it. ON CONFLICT lets Postgres serialise that
# decision instead of racing two callers against each other.
_UPSERT_PLAYER_SQL = """
INSERT INTO players (username, rating) VALUES (%s, %s)
ON CONFLICT (username) DO UPDATE SET rating = EXCLUDED.rating
"""

# Same race as _UPSERT_PLAYER_SQL, same fix: two connections racing to
# register the same brand-new username must not both succeed. DO NOTHING
# plus RETURNING is what lets create_player tell "I created it" apart from
# "someone/something already had that name" from a single round trip.
_CREATE_PLAYER_SQL = """
INSERT INTO players (username, rating, pw_hash, salt) VALUES (%s, %s, %s, %s)
ON CONFLICT (username) DO NOTHING
RETURNING username
"""

_GET_PASSWORD_SQL = "SELECT pw_hash, salt FROM players WHERE username = %s"

# One UPDATE, not two: both ratings change or neither does. A CASE keyed
# on username, rather than two separate statements sharing one commit, is
# what makes this a single round trip as well as a single transaction.
_UPDATE_RATINGS_SQL = """
UPDATE players SET rating = CASE username
    WHEN %s THEN %s
    WHEN %s THEN %s
END
WHERE username IN (%s, %s)
"""


def connect(url=None, connector=None):
    """Open a connection to Postgres. `url` defaults to the DATABASE_URL
    environment variable; raises rather than silently falling through to
    psycopg's own default parameters, which could reach the wrong database.
    `connector` (the callable that opens the connection) is injected, so
    this can be tested with no live database and no patching."""
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL is not set and no url was given")
    connector = connector or _connect
    return connector(url)


def _connect(url):  # pragma: no cover -- needs a live Postgres to exercise
    return psycopg.connect(url)


def ensure_schema(conn):
    """Create the players table if it does not already exist, and add the
    pw_hash/salt columns if the table exists but predates them (an
    upgrade from before passwords existed)."""
    with conn.cursor() as cur:
        cur.execute(_ENSURE_SCHEMA_SQL)
    conn.commit()


def get_rating(conn, username):
    """-> the stored rating for `username`, or None if no such player.

    Parameterised (%s), never string-formatted: a hand-built query string
    embedding `username` directly would be a SQL injection hole."""
    with conn.cursor() as cur:
        cur.execute(_GET_RATING_SQL, (username,))
        row = cur.fetchone()
    return row[0] if row is not None else None


def upsert_player(conn, username, rating=DEFAULT_RATING):
    """Insert a new player at `rating`, or update an existing one's rating --
    in the one statement above (_UPSERT_PLAYER_SQL), never a SELECT
    followed by an INSERT. Parameterised (%s), never string-formatted, for
    the same reason as get_rating. -> the stored rating."""
    with conn.cursor() as cur:
        cur.execute(_UPSERT_PLAYER_SQL, (username, rating))
    conn.commit()
    return rating


def _hash_password(password, salt):
    """-> the PBKDF2-HMAC-SHA256 digest of `password` under `salt`, as
    bytes. Never called with a fresh salt when checking an existing
    password -- see verify_password -- since a different salt always
    produces a different digest even for the same password."""
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)


def create_player(conn, username, password):
    """Create a brand-new account for `username`/`password`, at
    DEFAULT_RATING. -> True if created, False if `username` already exists
    (the caller should fall back to verify_password instead). Never stores
    `password` itself: a fresh random salt and the PBKDF2 digest of the
    two together go into the row instead, as parameters."""
    salt = secrets.token_bytes(_SALT_BYTES)
    pw_hash = _hash_password(password, salt)
    with conn.cursor() as cur:
        cur.execute(_CREATE_PLAYER_SQL, (username, DEFAULT_RATING, pw_hash, salt))
        created = cur.fetchone() is not None
    conn.commit()
    return created


def verify_password(conn, username, password):
    """-> whether `password` matches the stored password for `username`.
    False, not raised, if `username` does not exist. Recomputes the digest
    from the stored salt and compares with hmac.compare_digest, not `==`,
    since `==` short-circuits at the first differing byte -- the timing
    side-channel a constant-time comparison exists to close."""
    with conn.cursor() as cur:
        cur.execute(_GET_PASSWORD_SQL, (username,))
        row = cur.fetchone()
    if row is None:
        return False
    stored_hash, salt = row
    candidate_hash = _hash_password(password, bytes(salt))
    return hmac.compare_digest(bytes(stored_hash), candidate_hash)


def update_ratings(conn, white_user, black_user, white_rating, black_rating):
    """Write both players' new ratings in the one statement above
    (_UPDATE_RATINGS_SQL) -- never two separate UPDATEs, which could leave
    one applied and the other not if something failed in between.
    Parameterised (%s), never string-formatted, for the same reason as
    get_rating/upsert_player."""
    with conn.cursor() as cur:
        cur.execute(_UPDATE_RATINGS_SQL, (
            white_user, white_rating, black_user, black_rating,
            white_user, black_user,
        ))
    conn.commit()
