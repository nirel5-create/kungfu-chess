import re
import sys

TOKEN_RE = re.compile(r"^[wb][KQRBNP]$")


def parse_sections(lines):
    board_start = lines.index("Board:") + 1
    commands_start = lines.index("Commands:")
    board = [line.split() for line in lines[board_start:commands_start] if line.strip()]
    commands = [line for line in lines[commands_start + 1:] if line.strip()]
    return board, commands


def validate_board(board):
    widths = {len(row) for row in board}
    if len(widths) > 1:
        return "ERROR ROW_WIDTH_MISMATCH"
    for row in board:
        for tok in row:
            if tok != "." and not TOKEN_RE.match(tok):
                return "ERROR UNKNOWN_TOKEN"
    return None


def render_board(board):
    return "\n".join(" ".join(row) for row in board)


def main():
    lines = sys.stdin.read().splitlines()
    board, commands = parse_sections(lines)
    error = validate_board(board)
    if error:
        print(error)
        return
    for cmd in commands:
        if cmd == "print board":
            print(render_board(board))


if __name__ == "__main__":
    main()
