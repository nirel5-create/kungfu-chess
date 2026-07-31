import pytest

from common.elo import K_FACTOR, expected_score, new_ratings


def test_equal_ratings_give_an_expected_score_of_exactly_half():
    assert expected_score(1200, 1200) == 0.5
    assert expected_score(1600, 1600) == 0.5


def test_a_much_higher_rating_gives_an_expected_score_close_to_one():
    assert expected_score(2400, 1200) > 0.99


def test_expected_scores_of_a_pair_sum_to_one():
    for a, b in [(1200, 1200), (1400, 1200), (1000, 1600), (2400, 800), (1201, 1199)]:
        assert expected_score(a, b) + expected_score(b, a) == pytest.approx(1.0)


def test_the_winner_gains_and_the_loser_loses():
    white, black = new_ratings(1200, 1200, "w")
    assert white > 1200
    assert black < 1200


def test_the_gain_and_the_loss_are_equal_in_size():
    white, black = new_ratings(1200, 1200, "w")
    assert (white - 1200) == -(black - 1200)

    white, black = new_ratings(1400, 1600, "b")
    assert (white - 1400) == -(black - 1600)


def test_beating_a_much_stronger_opponent_gains_more_than_beating_an_equal_one():
    _white_vs_equal, _ = new_ratings(1200, 1200, "w")
    gain_vs_equal = _white_vs_equal - 1200

    white_vs_stronger, _ = new_ratings(1200, 1800, "w")
    gain_vs_stronger = white_vs_stronger - 1200

    assert gain_vs_stronger > gain_vs_equal


def test_beating_a_much_weaker_opponent_gains_little():
    white, _black = new_ratings(1800, 1200, "w")
    assert 0 < (white - 1800) <= 2


def test_winner_none_returns_both_ratings_unchanged():
    assert new_ratings(1200, 1400, None) == (1200, 1400)


def test_results_are_integers_not_floats():
    white, black = new_ratings(1200, 1200, "w")
    assert isinstance(white, int)
    assert isinstance(black, int)


def test_a_custom_k_scales_the_change():
    white_default, _ = new_ratings(1200, 1200, "w")
    white_small_k, _ = new_ratings(1200, 1200, "w", k=8)
    assert (white_default - 1200) == 4 * (white_small_k - 1200)


def test_default_k_factor_is_32():
    assert K_FACTOR == 32
