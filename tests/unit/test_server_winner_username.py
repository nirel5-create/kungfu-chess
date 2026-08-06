from server import _winner_username


def test_winner_username_finds_the_user_seated_in_the_winning_color():
    seats = {"alice": "w", "bob": "b"}
    assert _winner_username(seats, "w") == "alice"


def test_winner_username_is_none_when_there_is_no_winner():
    seats = {"alice": "w", "bob": "b"}
    assert _winner_username(seats, None) is None
