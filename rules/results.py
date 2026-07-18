from collections import namedtuple

# Guide S8: reason is always present. "ok" when the move is valid; otherwise a
# stable, machine-readable string that unit tests can assert on.
MoveValidation = namedtuple("MoveValidation", "is_valid reason")

REASON_OK = "ok"
REASON_OUTSIDE_BOARD = "outside_board"
REASON_EMPTY_SOURCE = "empty_source"
REASON_FRIENDLY_DESTINATION = "friendly_destination"
REASON_ILLEGAL_PIECE_MOVE = "illegal_piece_move"

VALID = MoveValidation(True, REASON_OK)
