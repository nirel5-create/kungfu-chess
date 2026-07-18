# Repo:   https://github.com/nirel5-create/kungfu-chess
# Report: https://nirel5-create.github.io/kungfu-chess/ARCHITECTURE_REPORT.html
#         (interactive, rendered architecture report)
"""Entry point for the text protocol. Reads a script on stdin, writes the
board on stdout. It composes the objects and hands over -- it holds no game
logic, no text format, and no command meanings of its own."""
import sys

from model.config import Config
from texttests.script_runner import ScriptRunner

# Re-exported for callers that already import them from here.
from texttests.script_runner import ERROR_ROW_WIDTH, ERROR_UNKNOWN_TOKEN

__all__ = ["run", "ERROR_ROW_WIDTH", "ERROR_UNKNOWN_TOKEN"]


def run(inp, out):
    ScriptRunner(Config(), out).run(inp.read())


if __name__ == "__main__":
    run(sys.stdin, sys.stdout)  # pragma: no cover
