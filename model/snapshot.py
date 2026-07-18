from collections import namedtuple

# What the renderer draws. A read-only view model (guide S12): the renderer
# receives this and never a live Board or Piece, so it cannot mutate game state
# by accident and stays decoupled from how the model is stored.
#
#   kind   / color   piece identity, for picking a sprite
#   row    / col     logical cell -- where the board says it is
#   x      / y       pixel position; interpolated while in flight, so the
#                    renderer can draw a piece between cells (guide S10)
#   state  idle / moving / captured -- Piece.state, the lifecycle flag only
PieceView = namedtuple("PieceView", "kind color row col x y state")

GameSnapshot = namedtuple(
    "GameSnapshot", "board_width board_height cell_size pieces selected_cell game_over")

STATE_IDLE = "idle"
STATE_MOVING = "moving"
STATE_CAPTURED = "captured"
