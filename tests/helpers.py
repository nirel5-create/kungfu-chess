"""Shared test helpers. One place, so no test file re-invents them.

Nothing here patches or replaces anything at runtime: fakes are handed in
through constructors, which is the whole reason the classes take their
collaborators as arguments.
"""
from model.config import Config
from engine.game import GameEngine
from input.board_mapper import BoardMapper
from input.controller import Controller

CFG = Config()

# The class was called MoveValidator before the guide's names were adopted.
# Older tests still say it.
from rules.rules import RuleEngine as MoveValidator  # noqa: E402,F401

__all__ = [
    "CFG", "FakeEngine", "MoveValidator", "cell_center", "make_game",
    "render", "run_fixture", "wait_for",
]


def render(board):
    """The board as text. The format lives in BoardPrinter -- Board itself does
    not know how it is printed, which keeps model free of any io dependency."""
    from boardio.board_printer import BoardPrinter
    return BoardPrinter().print(board)


def make_game(board, config):
    """Compose the stack exactly as the script runner does. Returns the pair a
    test needs: the engine (commands, time) and the controller (clicks)."""
    engine = GameEngine(board, config)
    controller = Controller(engine, BoardMapper(board, config), board, config)
    return engine, controller


def cell_center(col, row, config=CFG):
    """Pixel at the middle of a cell -- what a click on it would carry."""
    half = config.cell_size // 2
    return col * config.cell_size + half, row * config.cell_size + half


def wait_for(cells, config=CFG):
    """Milliseconds a piece needs to cross `cells` cells."""
    return cells * config.piece_speed_ms


def run_fixture(fixture):
    """Run a text script and return everything it printed."""
    import io as _io
    import main
    out = _io.StringIO()
    main.run(_io.StringIO(fixture), out)
    return out.getvalue()


class FakeEngine:
    """A stand-in for GameEngine. Guide S16 asks for exactly this: "Controller:
    Unit tests with a fake GameEngine." It works because the controller is
    handed its engine -- nothing is patched."""

    def __init__(self):
        self.moves = []
        self.jumps = []

    def request_move(self, src, dst):
        from engine.results import ACCEPTED
        self.moves.append((src, dst))
        return ACCEPTED

    def request_jump(self, cell):
        self.jumps.append(cell)
