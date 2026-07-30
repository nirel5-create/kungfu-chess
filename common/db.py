"""Postgres connection and schema for player ratings.

Server_Design.md section 10, Step A: prove the server and Postgres can talk,
and put the players schema in place. This module does not implement
accounts, login, or ELO arithmetic -- those are later steps; it only opens a
connection, ensures the schema exists, and reads/writes a rating.

What this module owns: opening a connection from DATABASE_URL, creating the
players schema if absent, and reading/writing a player's rating.
What it does NOT own: password hashing, ELO arithmetic, sessions, or any
game logic.
"""

import os

import psycopg

DEFAULT_RATING = 1200

_ENSURE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS players (
    username TEXT PRIMARY KEY,
    rating INTEGER NOT NULL DEFAULT 1200
)
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


def connect(url=None, connector=None):
    """Open a connection to Postgres. `url` defaults to the DATABASE_URL
    environment variable; raises a clear error if neither is given, rather
    than silently falling through to psycopg's own default connection
    parameters (which would likely reach the wrong database, or none at
    all).

    `connector` is the callable that actually opens the connection given a
    url, and defaults to the real psycopg connector below. It is injected --
    the same pattern as ClientProxy(send) and GameRegistry(make_session)
    elsewhere in this project -- so the URL-resolution logic above can be
    exercised by a test with no live database and no patching of this
    module's own code: a test just passes its own callable instead."""
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL is not set and no url was given")
    connector = connector or _connect
    return connector(url)


def _connect(url):  # pragma: no cover -- needs a live Postgres to exercise
    return psycopg.connect(url)


def ensure_schema(conn):
    """Create the players table if it does not already exist."""
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
