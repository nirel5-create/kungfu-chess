import unittest

from model.board import Board
from model.config import Config
from model.piece import Piece, STATE_MOVING, STATE_CAPTURED



class TestPiece(unittest.TestCase):
    """Guide S6 + S17 Iteration 1."""

    def setUp(self):
        self.config = Config()
        self.board = Board([["wR", ".", "bK"]], self.config)

    def test_a_piece_knows_what_and_where_it_is(self):
        p = self.board.piece_object_at(0, 0)
        self.assertEqual((p.color, p.kind), ("w", "R"))
        self.assertEqual(p.cell, (0, 0))
        self.assertEqual(p.token, "wR")

    def test_an_empty_cell_has_no_piece(self):
        self.assertIsNone(self.board.piece_object_at(0, 1))

    def test_piece_state_is_a_lifecycle_flag_only(self):
        p = self.board.piece_object_at(0, 0, STATE_MOVING)
        self.assertEqual(p.state, STATE_MOVING)
        # It carries no timing or destination data -- those live on Motion.
        self.assertEqual(set(Piece.__slots__), {"piece_id", "color", "kind", "cell", "state"})
        p.state = STATE_CAPTURED
        self.assertEqual(p.state, STATE_CAPTURED)

    def test_pieces_are_identified_by_id_not_by_token(self):
        # Two rooks read the same; they are still different pieces. This is the
        # gap that token comparison cannot see.
        board = Board([["wR", "wR"]], self.config)
        a, b = board.piece_object_at(0, 0), board.piece_object_at(0, 1)
        self.assertEqual(a.token, b.token)
        self.assertNotEqual(a, b)
        self.assertNotEqual(a.piece_id, b.piece_id)

    def test_ids_are_unique_across_the_board(self):
        board = Board([["wR", "wR", "wN"], ["bK", ".", "wR"]], self.config)
        ids = [p.piece_id for p in board.pieces()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_a_piece_never_knows_about_pixels_or_rendering(self):
        self.assertNotIn("x", Piece.__slots__)
        self.assertNotIn("y", Piece.__slots__)

    def test_board_lists_every_piece(self):
        self.assertEqual(sorted(p.token for p in self.board.pieces()), ["bK", "wR"])

    def test_a_piece_is_never_equal_to_a_non_piece(self):
        self.assertNotEqual(self.board.piece_object_at(0, 0), "wR")

    def test_pieces_are_hashable_by_identity(self):
        board = Board([["wR", "wR"]], self.config)
        a, b = board.piece_object_at(0, 0), board.piece_object_at(0, 1)
        self.assertEqual(len({a, b, board.piece_object_at(0, 0)}), 2)

    def test_repr_is_readable(self):
        self.assertIn("kind='R'", repr(self.board.piece_object_at(0, 0)))


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
