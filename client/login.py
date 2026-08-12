"""Terminal login (before the window opens) and the two polling waits that
follow it: for a login refusal, and for a seat once a room choice is sent.
"""

import getpass
import time

from client.homescreen import HomeFlow
from client.link import _ServerLink
from common.logsetup import add_file_logging, sanitize_for_filename

_SERVER_URI = "ws://localhost:8765"
_LOG_DIR = "logs"


def _prompt_username(mention_quit=False):  # pragma: no cover
    """Read a username from the terminal. -> the typed text, stripped --
    including "" or "q" unchanged rather than re-prompting on either: the
    login retry loop treats both as "quit". `mention_quit` is True only
    for the first prompt of an attempt, since repeating the way out after
    every refusal read as a reprinted paragraph rather than one line."""
    prompt = 'Username (blank or "q" to quit): ' if mention_quit else "Username: "
    return input(prompt).strip()


def _prompt_password():  # pragma: no cover
    """Read a password from the terminal. Uses getpass.getpass rather
    than input() so the password is never echoed to the screen or
    terminal scrollback. An empty password is sent as typed: the server
    accepts any password for a brand-new username, so there is nothing
    here to validate."""
    return getpass.getpass("Password: ")


def _client_log_path(username):  # pragma: no cover
    """-> the per-client log file path for `username`, e.g.
    "logs/client_alice.log". One file per client rather than one shared
    log: concurrent appends from several clients would interleave
    unrelated sessions and are not safe on Windows besides. `username` is
    free text typed at a prompt, so it is sanitized first."""
    return f"{_LOG_DIR}/client_{sanitize_for_filename(username)}.log"


def _login():  # pragma: no cover
    """Prompt for username/password, retrying on a refusal instead of
    exiting. A fresh _ServerLink is built per attempt -- safe, since a
    refused login reserves nothing server-side. -> (flow, link) once
    login succeeds, or (flow, None) if the player quit. File logging
    starts only after a real success, so failures don't scatter it."""
    flow = HomeFlow()
    first_attempt = True
    while True:
        username = _prompt_username(mention_quit=first_attempt)
        first_attempt = False
        if not username or username.lower() == "q":
            return flow, None
        password = _prompt_password()
        link = _ServerLink(_SERVER_URI, username, password)
        link.start()
        _wait_for_login_error(link)
        if link.error() is None:
            add_file_logging(_client_log_path(username))
            flow.logged_in(username)
            return flow, link
        print(f"Login refused: {link.error()}")
        flow.login_refused(link.error())


def _wait_for_login_error(link, timeout_s=2.0, poll_interval=0.02):  # pragma: no cover
    """Block for up to `timeout_s`, or until the network thread records a
    refusal, whichever is first. Called right after link.start(), before
    the Room dialog is shown, so a bad password is caught before the
    player wastes effort on it. Does not wait for color(): the server
    only seats a color once it also knows the room choice, sent later."""
    deadline = time.time() + timeout_s
    while link.error() is None and time.time() < deadline:
        time.sleep(poll_interval)


def _wait_for_assignment_or_error(link, poll_interval=0.02):  # pragma: no cover
    """Block until the network thread records either a seat (color()) or
    a refusal (error()) -- the two are mutually exclusive on the wire.
    Called after the room choice is sent, before the window opens. Unlike
    _wait_for_login_error, this has no fixed timeout: the server itself
    may be waiting on a slow human at the other end of a room dialog."""
    while link.color() is None and link.error() is None:
        time.sleep(poll_interval)
