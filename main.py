# Repo: https://github.com/nirel5-create/kungfu-chess
import sys

from config import Config
from board import Board
from game import Game

# Protocol output strings (single source of truth, never inline magic strings).
ERROR_ROW_WIDTH = "ERROR ROW_WIDTH_MISMATCH"
ERROR_UNKNOWN_TOKEN = "ERROR UNKNOWN_TOKEN"


def parse_sections(lines):
    lines = [line.strip() for line in lines]
    board_start = lines.index("Board:") + 1
    commands_start = lines.index("Commands:")
    grid = [line.split() for line in lines[board_start:commands_start] if line]
    commands = [line for line in lines[commands_start + 1:] if line]
    return grid, commands


def validate_board(grid, config):
    widths = {len(row) for row in grid}
    if len(widths) > 1:
        return ERROR_ROW_WIDTH
    for row in grid:
        for token in row:
            if not config.is_valid_token(token):
                return ERROR_UNKNOWN_TOKEN
    return None


def dispatch(game, command, out):
    parts = command.split()
    if command == "print board":
        print(game.render(), file=out)
    elif parts[0] == "click" and len(parts) == 3:
        game.click(int(parts[1]), int(parts[2]))
    elif parts[0] == "wait" and len(parts) == 2:
        game.wait(int(parts[1]))
    # anything else -> ignored


def run(inp, out):
    lines = inp.read().splitlines()
    grid, commands = parse_sections(lines)
    config = Config()
    error = validate_board(grid, config)
    if error:
        print(error, file=out)
        return
    game = Game(Board(grid, config), config)
    for command in commands:
        dispatch(game, command, out)


if __name__ == "__main__":
    run(sys.stdin, sys.stdout)  # pragma: no cover