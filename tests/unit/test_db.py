import pytest

from common import db


class _FakeCursor:
    """Records every executed statement and its parameters, and returns a
    fixed row from fetchone -- a fake, not a mock of psycopg's own cursor,
    per the house rule of injecting a collaborator rather than patching a
    library."""

    def __init__(self, fetch_result=None):
        self.queries = []
        self._fetch_result = fetch_result

    def execute(self, sql, params=None):
        self.queries.append((sql, params))

    def fetchone(self):
        return self._fetch_result

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def __init__(self, fetch_result=None):
        self.cursor_obj = _FakeCursor(fetch_result)
        self.committed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True


def test_default_rating_is_1200():
    assert db.DEFAULT_RATING == 1200


def test_connect_raises_a_clear_error_when_database_url_is_absent(monkeypatch):
    # monkeypatch.delenv sets an environment variable -- process-global
    # state, not a collaborator db.py takes as an argument -- so this is not
    # the patching the mentor forbade. There is also no other way to
    # exercise "DATABASE_URL absent": os.environ has to actually be missing
    # the key for this branch to run.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError):
        db.connect()


def test_connect_passes_an_explicit_url_to_the_injected_connector():
    # No monkeypatching: `connector` is a real parameter of connect(), so a
    # test just passes its own callable, the same way a test hands
    # ClientProxy a list's .append or GameRegistry a fake make_session.
    seen = []
    result = db.connect(url="postgresql://example/db",
                         connector=lambda url: seen.append(url) or "a connection")
    assert seen == ["postgresql://example/db"]
    assert result == "a connection"


def test_connect_falls_back_to_the_database_url_env_var(monkeypatch):
    # Same distinction as the "absent" test above: setting the env var is
    # state, not a patch, and it is the only way to exercise this branch.
    monkeypatch.setenv("DATABASE_URL", "postgresql://from-env/db")
    assert db.connect(connector=lambda url: url) == "postgresql://from-env/db"


def test_ensure_schema_issues_one_statement_and_commits():
    conn = _FakeConnection()
    db.ensure_schema(conn)
    assert len(conn.cursor_obj.queries) == 1
    sql, _params = conn.cursor_obj.queries[0]
    assert "CREATE TABLE IF NOT EXISTS players" in sql
    assert conn.committed


def test_get_rating_returns_none_for_an_unknown_player():
    conn = _FakeConnection(fetch_result=None)
    assert db.get_rating(conn, "nobody") is None


def test_get_rating_returns_the_stored_int_for_a_known_player():
    conn = _FakeConnection(fetch_result=(1350,))
    assert db.get_rating(conn, "alice") == 1350


def test_get_rating_query_is_parameterised_not_f_string_interpolated():
    conn = _FakeConnection(fetch_result=None)
    username = "'; DROP TABLE players; --"
    db.get_rating(conn, username)
    sql, params = conn.cursor_obj.queries[0]
    assert "%s" in sql
    assert username not in sql
    assert params == (username,)


def test_upsert_player_issues_exactly_one_statement_using_on_conflict():
    conn = _FakeConnection()
    result = db.upsert_player(conn, "alice", rating=1400)
    assert len(conn.cursor_obj.queries) == 1
    sql, params = conn.cursor_obj.queries[0]
    assert "ON CONFLICT" in sql
    assert params == ("alice", 1400)
    assert result == 1400
    assert conn.committed


def test_upsert_player_defaults_to_default_rating_when_none_given():
    conn = _FakeConnection()
    result = db.upsert_player(conn, "bob")
    assert result == db.DEFAULT_RATING


def test_upsert_player_query_is_parameterised_not_f_string_interpolated():
    conn = _FakeConnection()
    username = "'; DROP TABLE players; --"
    db.upsert_player(conn, username)
    sql, params = conn.cursor_obj.queries[0]
    assert "%s" in sql
    assert username not in sql
    assert params[0] == username
