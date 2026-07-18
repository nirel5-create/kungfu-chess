"""Headless game simulation.

Plays a scripted game and dumps one frame per tick as JSON: the logical board,
plus every piece in flight with its interpolated pixel position. That is exactly
the data a renderer needs, so this doubles as a proof that the snapshot seam is
sufficient before any drawing code exists.

Run:  PYTHONPATH=. python tools/simulate.py > frames.json
"""
import json
import sys

from model.config import Config
from model.board import Board
from engine.game import GameEngine


def frame(game, board, config, t):
    """One tick, exactly as the renderer receives it: the engine's own snapshot."""
    s = game.snapshot()
    return {"t": t,
            "pieces": [{"token": p.color + p.kind, "row": p.row, "col": p.col,
                        "x": round(p.x, 1), "y": round(p.y, 1),
                        "moving": p.state == "moving"} for p in s.pieces],
            "game_over": s.game_over}


def run(script, rows=5, cols=5, tick=100):
    config = Config()
    board = Board([["." for _ in range(cols)] for _ in range(rows)], config)
    for cell, tok in script["setup"].items():
        board.set_piece(tuple(cell), tok)
    game = GameEngine(board, config)

    frames = []
    t = 0
    events = sorted(script["moves"], key=lambda m: m["at"])
    i = 0
    while t <= script["duration"]:
        while i < len(events) and events[i]["at"] <= t:
            e = events[i]
            game.request_move(tuple(e["src"]), tuple(e["dst"]))
            i += 1
        frames.append(frame(game, board, config, t))
        game.wait(tick)
        t += tick
    return {"rows": rows, "cols": cols, "cell": config.cell_size, "frames": frames}


DEMO = {
    "setup": {(0, 0): "bR", (0, 4): "bK", (4, 0): "wK", (4, 4): "wR", (2, 2): "bP"},
    # Three pieces set off at once -- the whole point of the per-piece model.
    "moves": [
        {"at": 0,    "src": (4, 4), "dst": (0, 4)},   # wR hunts the black king
        {"at": 0,    "src": (0, 0), "dst": (4, 0)},   # bR hunts the white king
        {"at": 500,  "src": (2, 2), "dst": (3, 2)},   # a pawn strolls, meanwhile
    ],
    "duration": 4000,
}

if __name__ == "__main__":
    json.dump(run(DEMO), sys.stdout)
