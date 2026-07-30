"""Shared file-logging setup for server.py and client.py.

Slide 6: "Store logs on both server and client side, for all of the
client/server activity." Both sides already log to the console via
logging.basicConfig -- that is fine for watching a session live, but
nothing was ever written down, so there was nothing left to inspect
afterward. This module is the fix: one place that adds a file destination,
shared rather than duplicated per side, so the two log files cannot drift
into different timestamp/level/message formats.

What this module owns: building and attaching a logging.FileHandler with a
fixed format, creating the log file's folder if it does not exist yet.
What it does NOT own: deciding WHAT gets logged (that is server.py's and
client.py's own _log.info/.warning/.exception calls at each call site) or
removing/replacing the console handler -- the two destinations are meant to
run side by side, not compete.
"""

import logging
import os
import re

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_UNSAFE_FOR_FILENAME = re.compile(r"[^A-Za-z0-9_-]")


def add_file_logging(log_path):
    """Add a logging.FileHandler at `log_path` to the root logger,
    formatted as timestamp, level and message (plus the logger's own name,
    since server.py and client.py -- and anything under common/ that logs
    -- all end up sharing one file). Creates `log_path`'s parent directory
    first if it does not exist yet, so a fresh checkout does not need a
    logs/ folder created by hand before the first run.

    Attaches to the ROOT logger rather than a specific one, and only ADDS
    this handler -- it never removes or replaces whatever is already
    there (namely the console handler logging.basicConfig installs) -- so
    every existing and future logger call reaches both destinations, and
    console output keeps working exactly as it did before this was added.

    -> the FileHandler that was created and attached, so a caller (a test,
    mainly) that wants to remove and close it explicitly can."""
    directory = os.path.dirname(log_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_FORMAT))
    logging.getLogger().addHandler(handler)
    return handler


def sanitize_for_filename(name):
    """-> `name` with every character that is not a letter, digit, dash or
    underscore replaced by "_".

    client.py builds one log file per client from the username the player
    typed at the terminal prompt (logs/client_<username>.log) -- multiple
    clients sharing one file interleaves unrelated sessions with nothing
    to tell them apart, and concurrent appends from separate processes are
    not safe on Windows besides. But a username is free text: unsanitized,
    "../server" or "a/b" would escape the logs/ folder entirely, and other
    characters (":", "*", ...) are simply illegal in a Windows filename.
    This is the one pure piece of that fix, so it is the one that gets
    tests -- building the actual path and opening the file stays in
    client.py's untested socket-level code."""
    return _UNSAFE_FOR_FILENAME.sub("_", name)
