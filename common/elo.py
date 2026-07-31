"""ELO rating arithmetic (slide 4: "Add rating (starting from 1200, moving up
and down by ELO)").

No database, no I/O, no logging -- this is the one piece of Step 8 that is
entirely pure and testable, so it is the one that gets thorough tests.
Everything else (common/db.py, server.py) is wiring around this.

What this module owns: the standard ELO formulas -- expected score and the
resulting rating change.
What it does NOT own: reading or writing a rating (common/db.py), or
deciding when a game's result is final (server.py's GAME_END subscriber).
"""

K_FACTOR = 32


def expected_score(rating, opponent_rating):
    """-> the probability (in (0, 1)) that `rating` beats `opponent_rating`,
    per the standard logistic ELO formula. Symmetric: expected_score(a, b)
    + expected_score(b, a) == 1 (up to floating-point rounding)."""
    return 1 / (1 + 10 ** ((opponent_rating - rating) / 400))


def new_ratings(white, black, winner, k=K_FACTOR):
    """-> (new_white, new_black), both integers.

    `winner` is "w", "b", or None. None means a game with no result -- an
    infrastructure failure, a game abandoned by both players -- and must
    return `white`/`black` unchanged: Server_Design.md calls this "a game
    that is not counted", not a draw, and a draw would still move ratings.

    The two changes are computed as a single delta, rounded exactly once,
    then applied as +delta / -delta -- never as two independently-rounded
    numbers. white's raw (unrounded) change and black's are exact
    opposites by the ELO formula (expected_score(a, b) == 1 -
    expected_score(b, a), and the actual scores are 1 and 0 in some
    order), but rounding each side on its own can still make the rounded
    pair NOT sum to zero (e.g. a raw change of +3.5 could round to +4 while
    its exact opposite, -3.5, rounds to -4 too) -- silently leaking or
    creating rating points across every game played. Rounding one delta
    once and applying it symmetrically makes that impossible by
    construction."""
    if winner is None:
        return white, black
    white_actual = 1 if winner == "w" else 0
    delta = round(k * (white_actual - expected_score(white, black)))
    return white + delta, black - delta
