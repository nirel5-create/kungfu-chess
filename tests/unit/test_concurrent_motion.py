import unittest

from engine.game import GameEngine
from model.board import Board
from model.config import Config
from realtime.arbiter import RealTimeArbiter
from tests.helpers import make_game, render



class TestConcurrentMotion(unittest.TestCase):
    """Concurrency is core behaviour: the block applies only to the piece that
    is currently moving. Every other piece, on both sides, stays free."""

    def setUp(self):
        self.config = Config()

    # --- the mandatory rule, and its exact boundary -----------------------

    def test_moving_piece_cannot_be_re_commanded(self):
        board = Board([["wR", ".", ".", "."]], self.config)
        game, ctrl = make_game(board, self.config)
        game.request_move((0, 0), (0, 3))
        reason = game.request_move((0, 0), (0, 1))
        self.assertEqual(reason.reason, GameEngine.REASON_MOTION_IN_PROGRESS)

    def test_other_piece_may_move_while_one_is_moving(self):
        board = Board([["wR", ".", ".", "wQ"]], self.config)
        game, ctrl = make_game(board, self.config)
        game.request_move((0, 0), (0, 1))
        reason = game.request_move((0, 3), (0, 2))   # a different piece
        self.assertTrue(reason.is_accepted)
        self.assertEqual(game._rta.active_motion_count(), 2)

    def test_both_players_move_at_the_same_time(self):
        board = Board([["wR", ".", ".", "bR"]], self.config)
        game, ctrl = make_game(board, self.config)
        self.assertTrue(game.request_move((0, 0), (0, 1)).is_accepted)
        self.assertTrue(game.request_move((0, 3), (0, 2)).is_accepted)
        game.wait(1000)
        self.assertEqual(render(board), ". wR bR .")

    # --- arrival ordering -------------------------------------------------

    def test_arrivals_resolve_in_chronological_order(self):
        board = Board([["wR", ".", ".", "."],
                       ["wQ", ".", ".", "."]], self.config)
        game, ctrl = make_game(board, self.config)
        game.request_move((0, 0), (0, 3))   # 3 cells -> 3000ms
        game.request_move((1, 0), (1, 1))   # 1 cell  -> 1000ms
        arrivals = game._rta.advance_time(3000)
        self.assertEqual([m.arrival_time for m in arrivals], [1000, 3000])

    def test_simultaneous_arrivals_are_deterministic(self):
        board = Board([[".", "wR", "."],
                       [".", "wN", "."]], self.config)
        rta = RealTimeArbiter(board, self.config)
        rta.start_motion("wR", (0, 1), (0, 0))
        rta.start_motion("wN", (1, 1), (1, 0))
        first = [m.source for m in rta.advance_time(1000)]
        board2 = Board([[".", "wR", "."], [".", "wN", "."]], self.config)
        rta2 = RealTimeArbiter(board2, self.config)
        rta2.start_motion("wN", (1, 1), (1, 0))   # inserted in the other order
        rta2.start_motion("wR", (0, 1), (0, 0))
        second = [m.source for m in rta2.advance_time(1000)]
        self.assertEqual(first, second)

    # --- collisions between moving pieces ---------------------------------

    def test_later_arriver_captures_the_earlier_one(self):
        # bR lands on (0,3) at 1000ms; wR reaches the same cell at 3000ms and,
        # arriving later, captures it.
        board = Board([["wR", ".", ".", ".", "bR"]], self.config)
        game, ctrl = make_game(board, self.config)
        game.request_move((0, 0), (0, 3))   # 3 cells -> 3000ms
        game.request_move((0, 4), (0, 3))   # 1 cell  -> 1000ms
        game.wait(3000)
        self.assertEqual(render(board), ". . . wR .")

    def test_friendly_race_for_one_cell_cancels_the_late_arriver(self):
        # Both moves were legal when issued -- (0,2) was empty. wN lands first;
        # wR then arrives and finds a friend, so its arrival is cancelled.
        board = Board([["wR", ".", ".", "wQ"]], self.config)
        game, ctrl = make_game(board, self.config)
        game.request_move((0, 0), (0, 2))   # 2 cells -> 2000ms
        game.request_move((0, 3), (0, 2))   # 1 cell  -> 1000ms
        game.wait(2000)
        self.assertEqual(render(board), "wR . wQ .")

    def test_king_capture_by_later_arriver_ends_the_game(self):
        board = Board([["wR", ".", ".", ".", "bK"]], self.config)
        game, ctrl = make_game(board, self.config)
        game.request_move((0, 0), (0, 3))   # 3000ms
        game.request_move((0, 4), (0, 3))   # 1000ms -- bK lands first
        game.wait(3000)
        self.assertTrue(game.game_over)
        self.assertEqual(game.request_move((0, 3), (0, 2)).reason, GameEngine.REASON_GAME_OVER)

    def test_piece_captured_on_its_source_while_in_flight_is_dropped(self):
        # bR lands on wR's source cell at 1000ms and eats it. wR's motion must not
        # resolve at 3000ms -- doing so would teleport bR to (0,3).
        board = Board([["wR", ".", ".", "."],
                       ["bR", ".", ".", "."]], self.config)
        game, ctrl = make_game(board, self.config)
        game.request_move((0, 0), (0, 3))   # wR: 3 cells -> 3000ms
        game.request_move((1, 0), (0, 0))   # bR: 1 cell  -> 1000ms
        game.wait(1000)
        self.assertEqual(render(board), "bR . . .\n. . . .")
        game.wait(2000)
        self.assertEqual(render(board), "bR . . .\n. . . .")   # bR stays put

    def test_moving_king_captured_on_its_source_ends_the_game(self):
        # bR is strictly earlier, so it lands while the king is still logically
        # on its source cell and takes it there.
        board = Board([["wK", ".", ".", "."],
                       ["bR", ".", ".", "."]], self.config)
        game, ctrl = make_game(board, self.config)
        game.request_move((1, 0), (0, 0))   # bR: arrives at 1000
        game.wait(500)
        game.request_move((0, 0), (0, 1))   # wK: sets off later, arrives at 1500
        game.wait(500)                       # clock = 1000 -> bR lands on the king
        self.assertTrue(game.game_over)
        self.assertEqual(render(board), "bR . . .\n. . . .")
        game.wait(1000)                      # the dead king's motion never resolves
        self.assertEqual(render(board), "bR . . .\n. . . .")

    def test_simultaneous_arrival_at_a_source_lets_the_mover_leave_first(self):
        # Both land in the same millisecond, so neither is "later". The
        # deterministic order resolves the departure first and the arriver
        # simply takes the vacated cell -- nobody is captured.
        board = Board([["wR", ".", ".", "."],
                       ["bR", ".", ".", "."]], self.config)
        game, ctrl = make_game(board, self.config)
        game.request_move((0, 0), (0, 1))
        game.request_move((1, 0), (0, 0))
        game.wait(1000)
        self.assertEqual(render(board), "bR wR . .\n. . . .")

    def test_ghost_motion_cannot_teleport_an_identical_looking_piece(self):
        # wR#1 sets off on a long trip; bR takes it on its source cell; wR#2 then
        # takes bR and settles on that same cell. wR#1's queued motion must be gone
        # -- comparing tokens would not catch this, since both rooks read "wR".
        board = Board([["wR", ".", ".", ".", ".", "."],
                       ["bR", ".", ".", ".", ".", "."],
                       ["wR", ".", ".", ".", ".", "."]], self.config)
        game, ctrl = make_game(board, self.config)
        game.request_move((0, 0), (0, 5))   # wR#1: 5 cells -> 5000ms
        game.request_move((1, 0), (0, 0))   # bR: 1 cell -> 1000ms, takes wR#1
        game.wait(1000)
        game.request_move((2, 0), (0, 0))   # wR#2: 2 cells -> arrives at 3000
        game.wait(2000)
        self.assertEqual(board.piece_at(0, 0), "wR")
        game.wait(2000)                      # past wR#1's original arrival time
        self.assertEqual(board.piece_at(0, 0), "wR")   # wR#2 stayed put
        self.assertIsNone(board.piece_at(0, 5))        # nothing teleported

    def test_in_flight_pieces_never_land_after_game_over(self):
        # Found by the fuzzer (seed 3). In the old one-motion model this was
        # impossible: the motion that took the king was the only one in the air.
        # With concurrency, other pieces are still flying when the game ends.
        board = Board([["wR", ".", ".", "bK"],
                       ["wR", ".", ".", "."]], self.config)
        game, ctrl = make_game(board, self.config)
        game.request_move((1, 0), (1, 3))   # a long trip: 3 cells -> 3000ms
        game.request_move((0, 0), (0, 3))   # takes bK at 3000ms too
        game.wait(3000)
        self.assertTrue(game.game_over)
        frozen = render(board)
        game.wait(10000)                     # time must stop with the game
        self.assertEqual(render(board), frozen)

    def test_wait_slicing_does_not_change_the_outcome_after_a_king_capture(self):
        # Design Guide S17 (Iteration 5): "Partial wait followed by remaining wait
        # equals one full wait." A king capture must therefore stop arrivals inside
        # advance_time, not merely between calls.
        def build():
            board = Board([["wR", "bK", ".", ".", "."],
                           ["wR", ".", ".", ".", "."]], self.config)
            game, ctrl = make_game(board, self.config)
            game.request_move((0, 0), (0, 1))   # takes bK at 1000ms
            game.request_move((1, 0), (1, 4))   # would land at 4000ms
            return board, game

        board_a, game_a = build()
        game_a.wait(4000)
        board_b, game_b = build()
        game_b.wait(1000)
        game_b.wait(3000)
        self.assertEqual(render(board_a), render(board_b))
        self.assertEqual(board_a.piece_at(1, 0), "wR")   # never landed

    # --- jump still works alongside several motions -----------------------

    def test_reversal_still_fires_with_another_motion_in_flight(self):
        board = Board([["wR", "bR", ".", "."],
                       ["wQ", ".", ".", "."]], self.config)
        game, ctrl = make_game(board, self.config)
        ctrl.jump(0, 0)                      # wR at (0,0) goes airborne, window 1000ms
        game.request_move((1, 0), (1, 1))   # an unrelated motion, runs alongside
        game.request_move((0, 1), (0, 0))   # bR dives onto the airborne wR
        game.wait(1000)
        # bR is eaten mid-air by the jumper; the unrelated motion is unaffected.
        self.assertEqual(render(board), "wR . . .\n. wQ . .")


if __name__ == "__main__":
    unittest.main()
