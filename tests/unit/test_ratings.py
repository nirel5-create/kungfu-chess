from server import _update_ratings_on_game_end


class _FakeCursor:
    """Returns queued fetchone() results in the order they are consumed --
    _update_ratings_on_game_end calls get_rating twice, once per player,
    each needing its own answer, which a single fixed fetch_result (as
    tests/unit/test_db.py's own fake uses) cannot express. update_ratings
    itself never calls fetchone, so it never drains the queue."""

    def __init__(self, fetch_results=()):
        self.queries = []
        self._fetch_results = list(fetch_results)

    def execute(self, sql, params=None):
        self.queries.append((sql, params))

    def fetchone(self):
        return self._fetch_results.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def __init__(self, fetch_results=()):
        self.cursor_obj = _FakeCursor(fetch_results)
        self.committed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True


class _RaisingConnection:
    """A connection whose cursor() blows up the moment it is used -- for
    the "a database error is swallowed" test, where get_rating's very
    first call must fail."""

    def cursor(self):
        raise RuntimeError("Postgres is unreachable")


_PAYLOAD = {
    "game_id": "cocorico",
    "winner": "w",
    "seats": {"alice": "w", "bob": "b"},
}


def test_a_normal_win_updates_both_ratings_correctly():
    conn = _FakeConnection(fetch_results=[(1200,), (1200,)])
    _update_ratings_on_game_end(conn, _PAYLOAD)

    update_sql, update_params = conn.cursor_obj.queries[-1]
    assert "UPDATE players" in update_sql
    white_user, new_white, black_user, new_black, _, _ = update_params
    assert white_user == "alice"
    assert black_user == "bob"
    assert new_white > 1200
    assert new_black < 1200
    assert (new_white - 1200) == -(new_black - 1200)
    assert conn.committed


def test_winner_none_writes_nothing():
    conn = _FakeConnection()
    payload = {**_PAYLOAD, "winner": None}
    _update_ratings_on_game_end(conn, payload)
    assert conn.cursor_obj.queries == []


def test_a_game_with_only_one_seated_player_writes_nothing():
    conn = _FakeConnection()
    payload = {**_PAYLOAD, "seats": {"alice": "w"}}
    _update_ratings_on_game_end(conn, payload)
    assert conn.cursor_obj.queries == []


def test_viewers_are_ignored():
    conn = _FakeConnection(fetch_results=[(1200,), (1200,)])
    payload = {**_PAYLOAD, "seats": {"alice": "w", "bob": "b", "carol": "viewer"}}
    _update_ratings_on_game_end(conn, payload)

    _update_sql, update_params = conn.cursor_obj.queries[-1]
    assert "carol" not in update_params


def test_a_database_error_is_swallowed_not_raised():
    # Must not raise -- the tick loop that published GAME_END must keep
    # running even though this game's result could not be recorded.
    _update_ratings_on_game_end(_RaisingConnection(), _PAYLOAD)


def test_db_conn_none_writes_nothing():
    _update_ratings_on_game_end(None, _PAYLOAD)  # must not raise either


def test_an_unknown_player_skips_the_update_without_raising():
    # get_rating returning None -- possible if the database was
    # unreachable at that player's own login (see _authenticate). Both
    # ratings are looked up (2 queries: white, then black) but no UPDATE
    # ever runs, and nothing is committed.
    conn = _FakeConnection(fetch_results=[(1200,), None])
    _update_ratings_on_game_end(conn, _PAYLOAD)
    assert len(conn.cursor_obj.queries) == 2
    assert not conn.committed
