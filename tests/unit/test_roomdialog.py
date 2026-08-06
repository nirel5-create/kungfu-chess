from client.roomdialog import _outcome_known, normalize_room_name


class _FakeLink:
    """A minimal stand-in for _ServerLink's own three read-only accessors
    -- exactly what _outcome_known reads, and nothing else -- so its
    resolved-or-not decision can be tested with no window, no socket, and
    no lock, the same pure/tested split this project already keeps
    between a decision and the plumbing that drives it."""

    def __init__(self, status=None, color=None, error=None):
        self._status = status
        self._color = color
        self._error = error

    def matchmaking_status(self):
        return self._status

    def color(self):
        return self._color

    def error(self):
        return self._error


def test_surrounding_whitespace_is_stripped():
    assert normalize_room_name("  cocorico  ") == "cocorico"


def test_an_all_whitespace_name_normalizes_to_empty_string():
    assert normalize_room_name("   ") == ""


def test_an_empty_string_normalizes_to_empty_string():
    assert normalize_room_name("") == ""


def test_an_ordinary_name_is_unchanged():
    assert normalize_room_name("cocorico") == "cocorico"


def test_inner_spaces_are_preserved():
    assert normalize_room_name("  my room  ") == "my room"


# --- _outcome_known (live-testing fix: no window if already resolved) ------

def test_nothing_resolved_yet_is_not_known():
    assert _outcome_known(_FakeLink(status="searching")) is False


def test_a_found_status_is_known():
    assert _outcome_known(_FakeLink(status="found")) is True


def test_a_timeout_status_is_known():
    assert _outcome_known(_FakeLink(status="timeout")) is True


def test_a_seat_already_assigned_is_known_even_with_no_status_sent():
    # A returning player whose held seat is still theirs (Step 12) gets
    # `assigned` straight away, with no `matchmaking` message at all --
    # see show_matchmaking_progress's own docstring.
    assert _outcome_known(_FakeLink(status=None, color="w")) is True


def test_a_refusal_is_known():
    assert _outcome_known(_FakeLink(status="searching", error="bad_password")) is True
