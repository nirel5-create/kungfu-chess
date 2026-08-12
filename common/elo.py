"""ELO rating arithmetic: ratings start at 1200 and move up and down by ELO.

No database, no I/O, no logging -- this is the one part of rating handling
that is entirely pure and testable, so it is the one that gets thorough
tests. Everything else (common/db.py, server.py) is wiring around this.

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
    """-> (new_white, new_black), both integers. `winner` is "w", "b", or
    None; None leaves both unchanged (an uncounted game, not a draw --
    a draw would still move ratings). Computed as one delta, rounded
    once, then applied as +delta/-delta: rounding each side separately
    can leave the pair not summing to zero, leaking rating points."""
    if winner is None:
        return white, black
    white_actual = 1 if winner == "w" else 0
    delta = round(k * (white_actual - expected_score(white, black)))
    return white + delta, black - delta
