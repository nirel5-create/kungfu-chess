"""Shared file-logging setup for server.py and client.py.

Both sides already log to the console via logging.basicConfig -- fine for
watching a session live, but nothing was ever written down for later
inspection. This module adds a file destination, shared rather than
duplicated per side, so the two log files cannot drift into different
timestamp/level/message formats.

What this module owns: building and attaching a logging.FileHandler with a
fixed format, creating the log file's folder if it does not exist yet.
What it does NOT own: deciding WHAT gets logged (each call site's own
_log.info/.warning/.exception calls) or removing/replacing the console
handler -- the two destinations run side by side, not compete."""

import logging
import os
import re

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_UNSAFE_FOR_FILENAME = re.compile(r"[^A-Za-z0-9_-]")


def add_file_logging(log_path):
    """Add a logging.FileHandler at `log_path` to the root logger, so every
    existing and future logger call reaches it too, alongside the console
    handler (only ADDED, never removed or replaced). Creates `log_path`'s
    parent directory first if needed. -> the FileHandler, so a caller
    (mainly a test) can remove and close it."""
    directory = os.path.dirname(log_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_FORMAT))
    logging.getLogger().addHandler(handler)
    return handler


def sanitize_for_filename(name):
    """-> `name` with every character that is not a letter, digit, dash or
    underscore replaced by "_". A username is free text: unsanitized,
    "../server" or "a/b" could escape the logs/ folder entirely, and
    characters like ":" or "*" are illegal in a Windows filename."""
    return _UNSAFE_FOR_FILENAME.sub("_", name)
