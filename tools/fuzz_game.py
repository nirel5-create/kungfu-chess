"""Randomised game fuzzer.

VPL checks command -> output. It does not check that the game stays *sane* while
several pieces are in the air at once. This does: it plays thousands of random
games and, after every single step, asserts invariants that must hold no matter
what the players do or how the timing falls.

Run:  PYTHONPATH=. python tools/fuzz_game.py [games] [seed]
"""
import random
import sys

from model.config import Config
from model.board import Board
from boardio.board_printer import BoardPrinter
from engine.game import GameEngine


class InvariantError(AssertionError):
    pass


def all_cells(board):
    return [(r, c) for r in range(board.rows) for c in range(board.cols)]


def occupied(board):
    return {cell: board.piece_at(*cell) for cell in all_cells(board)
            if board.piece_at(*cell) is not None}


def legal_moves(game, board):
    """Brute force every source/destination pair through the real validator."""
    moves = []
    for src in all_cells(board):
        if board.piece_at(*src) is None:
            continue
        if game._rta.is_moving(src):
            continue
        for dst in all_cells(board):
            if src != dst and game._validator.is_legal(src, dst):
                moves.append((src, dst))
    return moves


def check(game, board, prev_count, log):
    cfg = game._config

    # INV-1: pieces are never created. Captures remove them; promotion replaces
    # a piece in place. The count may fall, never rise.
    count = len(occupied(board))
    if count > prev_count:
        raise InvariantError(f"piece count rose {prev_count} -> {count}")

    # INV-2: a moving piece stays logically on its source cell until it arrives
    # (Design Guide S10). So every active motion's source must still hold a piece
    # of the mover's colour. A violation means a stale/ghost motion is queued --
    # this is the invariant that catches a dead piece still holding a trip.
    for src, motion in game._rta._active_motions.items():
        here = board.piece_at(*src)
        if here is None:
            raise InvariantError(f"active motion from empty cell {src}: {motion}")
        if not cfg.same_color(here, motion.piece):
            raise InvariantError(
                f"ghost motion at {src}: cell holds {here!r} but motion carries "
                f"{motion.piece!r} -> {motion}")

    # INV-3: every token on the board is a token the config recognises.
    for cell, tok in occupied(board).items():
        if not cfg.is_valid_token(tok):
            raise InvariantError(f"invalid token {tok!r} at {cell}")

    # INV-4: once the game is over the board is frozen.
    if game.game_over and log["frozen"] is not None:
        if BoardPrinter().print(board) != log["frozen"]:
            raise InvariantError("board changed after game_over")

    # INV-5: a resting piece must refuse any move command. This guards the
    # mentor's rule that a piece recovering after a move or jump cannot act.
    for cell in list(game._rta._resting):
        if board.piece_at(*cell) is None:
            raise InvariantError(f"resting recorded on empty cell {cell}")
        for dst in all_cells(board):
            if dst != cell:
                result = game.request_move(cell, dst)
                if result.is_accepted:
                    raise InvariantError(
                        f"resting piece at {cell} accepted a move to {dst}")

    return count


def play_one(seed, steps=60):
    rng = random.Random(seed)
    cfg = Config()
    grid = [["." for _ in range(5)] for _ in range(5)]
    board = Board(grid, cfg)
    # A small, dense, deliberately collision-prone setup.
    board.set_piece((0, 0), "bK"); board.set_piece((0, 2), "bR")
    board.set_piece((0, 4), "bR"); board.set_piece((1, 1), "bP")
    board.set_piece((4, 0), "wK"); board.set_piece((4, 2), "wR")
    board.set_piece((4, 4), "wR"); board.set_piece((3, 3), "wP")
    game = GameEngine(board, cfg)

    log = {"frozen": None}
    count = len(occupied(board))

    for _ in range(steps):
        roll = rng.random()
        if roll < 0.55:                       # issue a move
            moves = legal_moves(game, board)
            if moves:
                src, dst = rng.choice(moves)
                game.request_move(src, dst)
        elif roll < 0.70:                     # send a piece airborne
            cells = [c for c in occupied(board)
                     if not game._rta.is_moving(c)]
            if cells:
                r, c = rng.choice(cells)
                game.request_jump((r, c))
        else:                                 # let time pass
            game.wait(rng.choice([1, 250, 499, 500, 501, 999, 1000, 1001, 2000]))

        if game.game_over and log["frozen"] is None:
            log["frozen"] = BoardPrinter().print(board)
        count = check(game, board, count, log)

    return game


def replay(seed, chunk):
    """Play a fixed script of random moves, advancing time in `chunk`-sized
    steps. Design Guide S17 Iteration 5 requires that a partial wait followed by
    the remaining wait equals one full wait, so the final board must not depend
    on how the waiting was sliced."""
    rng = random.Random(seed)
    cfg = Config()
    board = Board([["." for _ in range(5)] for _ in range(5)], cfg)
    board.set_piece((0, 0), "bK"); board.set_piece((0, 2), "bR")
    board.set_piece((0, 4), "bR"); board.set_piece((4, 0), "wK")
    board.set_piece((4, 2), "wR"); board.set_piece((4, 4), "wR")
    game = GameEngine(board, cfg)
    for _ in range(6):
        moves = legal_moves(game, board)
        if moves:
            src, dst = rng.choice(moves)
            game.request_move(src, dst)
    total = 6000
    for _ in range(total // chunk):
        game.wait(chunk)
    return BoardPrinter().print(board)


def check_time_slicing(games):
    """Same script, different wait granularity -> identical board."""
    for seed in range(games):
        ref = replay(seed, 6000)
        for chunk in (1, 250, 500, 1000, 3000):
            got = replay(seed, chunk)
            if got != ref:
                raise InvariantError(
                    f"time slicing changed the outcome (seed={seed}, chunk={chunk}):\n"
                    f"  one wait : {ref!r}\n  sliced   : {got!r}")


def main():
    games = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    base = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    over = 0
    for i in range(games):
        seed = base + i
        try:
            g = play_one(seed)
            over += 1 if g._game_over else 0
        except InvariantError as e:
            print(f"FAIL  seed={seed}\n  {e}")
            return 1
    try:
        check_time_slicing(min(games, 400))
    except InvariantError as e:
        print(f"FAIL  {e}")
        return 1
    print(f"OK  {games} games, no invariant broken "
          f"({over} ended in a king capture); time-slicing equivalence holds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
