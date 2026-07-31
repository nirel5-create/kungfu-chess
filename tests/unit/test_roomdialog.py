from client.roomdialog import normalize_room_name


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
