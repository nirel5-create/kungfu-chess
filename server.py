"""Entry point for the WebSocket server. See server/__init__.py's own
module docstring for what each piece under server/ owns; this file only
sets up process-level logging and starts server.composition.main().

Run with:  python server.py
"""
import asyncio
import logging

from common.logsetup import add_file_logging
from server.composition import LOG_PATH, main

if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    # Console (above) is for watching a session live; the file (below) is
    # for looking at one afterward. Shared with client/__main__.py, so the
    # two log files cannot drift into different formats.
    add_file_logging(LOG_PATH)
    # Docker's HEALTHCHECK (see Dockerfile) opens a bare TCP socket to our
    # port every 10s and closes it again without ever sending a WebSocket
    # handshake -- websockets logs that as an ERROR with a full traceback,
    # on its own "websockets.server" logger, every single time. That is
    # our own healthcheck probing the port, not a real error, and at one
    # every 10s it would drown out everything the log file is otherwise
    # useful for. Raising the level on that ONE logger -- not root, and
    # not our own module loggers, which keep logging at INFO exactly as
    # before -- is what silences just this noise and nothing else.
    logging.getLogger("websockets.server").setLevel(logging.CRITICAL)
    asyncio.run(main())
