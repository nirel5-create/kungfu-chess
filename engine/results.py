from collections import namedtuple

# Guide S9: reason is always present. "ok" for an accepted command; otherwise an
# application-level reason, or a rule-level reason copied from MoveValidation.
MoveResult = namedtuple("MoveResult", "is_accepted reason")

REASON_OK = "ok"
REASON_GAME_OVER = "game_over"
REASON_MOTION_IN_PROGRESS = "motion_in_progress"
REASON_AIRBORNE = "airborne"

ACCEPTED = MoveResult(True, REASON_OK)
