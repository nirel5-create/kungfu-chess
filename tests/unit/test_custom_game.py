import unittest

from model.board import Board
from model.config import Config
from tests.helpers import MoveValidator
from model.config import (
    Ray, TARGET_EMPTY, TARGET_ENEMY, _default_movement,
    _ORTHOGONAL, _DIAGONAL, _KNIGHT_DELTAS,
)



class TestCustomGameIsDataOnly(unittest.TestCase):
    """The stated future requirement (mentor email): users define their own
    games -- pieces, and how each piece moves. These tests are the proof that
    it costs zero source edits. If one of them ever needs a change in
    model/rules/realtime/engine, that promise has been broken."""

    def _movement(self):
        return _default_movement(_ORTHOGONAL, _DIAGONAL, _KNIGHT_DELTAS)

    def test_a_brand_new_piece_needs_only_a_config_entry(self):
        movement = self._movement()
        # "Dragon": glides up to three diagonally, but only captures straight.
        movement["D"] = (
            [Ray(dr, dc, max_steps=3, target=TARGET_EMPTY) for dr, dc in _DIAGONAL]
            + [Ray(dr, dc, max_steps=1, target=TARGET_ENEMY) for dr, dc in _ORTHOGONAL]
        )
        config = Config(piece_types=("K", "Q", "R", "B", "N", "P", "D"),
                        movement=movement)
        board = Board([["." for _ in range(8)] for _ in range(8)], config)
        board.set_piece((4, 4), "wD")
        board.set_piece((4, 5), "bP")
        board.set_piece((5, 5), "bP")
        v = MoveValidator(board, config)
        self.assertTrue(v.is_legal((4, 4), (1, 1)))    # three diagonal, empty
        self.assertFalse(v.is_legal((4, 4), (0, 0)))   # four -- out of range
        self.assertTrue(v.is_legal((4, 4), (4, 5)))    # captures straight
        self.assertFalse(v.is_legal((4, 4), (5, 5)))   # never captures diagonally

    def test_changing_an_existing_piece_needs_only_a_config_entry(self):
        movement = self._movement()
        movement["R"] = [Ray(dr, dc, max_steps=2) for dr, dc in _ORTHOGONAL]
        config = Config(movement=movement)
        board = Board([["." for _ in range(8)] for _ in range(8)], config)
        board.set_piece((6, 2), "wR")
        v = MoveValidator(board, config)
        self.assertTrue(v.is_legal((6, 2), (6, 4)))    # two is fine
        self.assertFalse(v.is_legal((6, 2), (6, 5)))   # three is not

    def test_pawn_can_reverse_instead_of_promoting(self):
        # The mentor's own example: "a pawn that reaches the last row starts
        # walking the other way instead of becoming another piece."
        movement = self._movement()
        movement["wP2"] = [Ray(1, 0, max_steps=1, target=TARGET_EMPTY)]
        config = Config(piece_types=("K", "Q", "R", "B", "N", "P", "2"),
                        movement=movement, promotions={"wP": "wP2"})
        board = Board([["." for _ in range(8)] for _ in range(8)], config)
        v = MoveValidator(board, config)
        promoted = config.promotion_target("wP", 0, board)
        self.assertEqual(promoted, "wP2")
        board.set_piece((0, 7), promoted)
        self.assertTrue(v.is_legal((0, 7), (1, 7)))    # now walks back down
        self.assertFalse(v.is_legal((0, 7), (0, 6)))   # and only that way


if __name__ == "__main__":
    unittest.main()
