from common.validation import MAX_NAME_LENGTH, is_displayable


def test_a_plain_name_is_displayable():
    assert is_displayable("alice") is True


def test_digits_dash_and_underscore_are_displayable():
    assert is_displayable("player_1-2") is True


def test_inner_spaces_are_kept_and_displayable():
    assert is_displayable("my room") is True


def test_leading_and_trailing_whitespace_is_stripped_before_checking():
    assert is_displayable("  alice  ") is True


def test_an_empty_name_is_not_displayable():
    assert is_displayable("") is False


def test_a_name_that_is_only_whitespace_is_not_displayable():
    assert is_displayable("   ") is False


def test_emoji_are_not_displayable():
    assert is_displayable("alice\U0001F600") is False


def test_punctuation_outside_dash_and_underscore_is_not_displayable():
    assert is_displayable("alice!") is False


def test_a_name_at_the_maximum_length_is_displayable():
    assert is_displayable("a" * MAX_NAME_LENGTH) is True


def test_a_name_over_the_maximum_length_is_not_displayable():
    assert is_displayable("a" * (MAX_NAME_LENGTH + 1)) is False


def test_a_name_over_the_maximum_length_only_before_stripping_is_displayable():
    # The limit applies to the stripped name, not the raw input -- padding
    # with whitespace must not be a way to sneak past it either way.
    padded = " " + "a" * MAX_NAME_LENGTH + " "
    assert is_displayable(padded) is True
