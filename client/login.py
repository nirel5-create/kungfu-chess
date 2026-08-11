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
    """Read a username from the terminal, before the window opens (slide
    3: login in a shell, not the GUI). -> the typed text, stripped --
    including "" (a blank Enter) or "q" unchanged, rather than re-
    prompting on either the way this used to: the login retry loop treats
    both as "quit", and re-prompting here out from under it would make
    that way out silently not work. Any other value is a candidate
    username, with no further validation here -- there is no server-side
    check beyond the field simply being present, so this is the only
    check there ever was.

    `mention_quit` -- True only for the first prompt of a login attempt
    (live-testing fix): the way out is real on every attempt, but saying
    so again after every single refusal turned one clear line into a
    reprinted paragraph -- see _login()'s own docstring. Stating it once,
    up front, is enough for a player to remember it for the rest of the
    retry loop."""
    prompt = 'Username (blank or "q" to quit): ' if mention_quit else "Username: "
    return input(prompt).strip()


def _prompt_password():  # pragma: no cover
    """Read a password from the terminal, right after the username (slide
    4). getpass.getpass, not input(): it does not echo what is typed,
    which plain input() would -- a password visible on screen (or in a
    terminal's scrollback/recording) is exactly the kind of detail a
    reviewer notices. Unlike the username, an empty password is sent as
    typed: the server treats a brand-new username as a signup with
    whatever password arrives (slide 4: "whatever password he writes,
    that is the password"), empty string included, so there is nothing
    here to validate."""
    return getpass.getpass("Password: ")


def _client_log_path(username):  # pragma: no cover
    """-> the per-client log file path for `username`, e.g.
    "logs/client_alice.log". One file per client, not one shared
    logs/client.log: several clients on the same machine appending to a
    single file interleaves unrelated sessions with nothing to tell them
    apart, and concurrent appends from separate processes are not safe on
    Windows besides. `username` is free text typed at the terminal prompt,
    so it is sanitized first -- see sanitize_for_filename's docstring for
    exactly what that guards against."""
    return f"{_LOG_DIR}/client_{sanitize_for_filename(username)}.log"


def _login():  # pragma: no cover
    """Prompt for username/password, retrying on a server refusal instead
    of exiting the process. A fresh _ServerLink is built and started for
    every attempt -- safe, since a refused login never reserved anything
    server-side (server.auth._reserve_username is only ever touched after
    a successful _authenticate), unlike reusing a connection ACROSS GAMES
    once one has already succeeded, which is what client.composition.run()
    is careful not to do.

    -> (flow, link), with `flow` already logged_in() and `link` already
    started, once a login succeeds. -> (flow, None) if the player quit
    instead (see _prompt_username's own docstring for the two ways to)
    -- `flow` stays at its own fresh starting state (LOGIN), with nothing
    more for the caller to do.

    Per-client file logging is configured only once, here, right after a
    login actually succeeds -- not per attempt, so a string of failed
    attempts before the real one does not scatter log lines across
    several files, or worse, build one from a rejected, possibly-bogus
    username.

    A refusal prints just the reason (e.g. "Login refused: bad_password")
    -- live testing found the original message ("...Try again, or leave
    the username blank (or type "q") to quit.") read as a paragraph
    reprinted after every failed attempt; the way out is stated once, in
    the very first username prompt (_prompt_username's own
    mention_quit), which is enough to remember for the rest of the
    loop."""
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
    refusal (error() becomes non-None) -- whichever is first. Called right
    after link.start(), before the Room dialog is ever shown, so a bad
    password is caught before the player wastes any effort on a dialog
    that was never going to matter. Only "bad_password" can arrive this
    early: AlreadyConnectedError (server.connection._handle_client) is
    scoped to a specific game_id, which is not known until the room choice
    is sent below, so that refusal cannot fire before this function
    returns -- it is still caught, just by
    _wait_for_assignment_or_error afterward.

    Does NOT wait for color(): unlike _wait_for_assignment_or_error below,
    nothing has been assigned yet at this point, on purpose -- the server
    only proceeds past the login check to seat a color once it also knows
    the room choice (see server.connection._handle_client), which this
    function is called before making. `timeout_s` only needs to
    comfortably cover _authenticate's own cost (one hashed password
    comparison, tens of milliseconds) -- the server sends `error` for a
    bad password the moment it knows, with no artificial delay of its
    own, so this is a generous multiple of that, not a guess at network
    latency."""
    deadline = time.time() + timeout_s
    while link.error() is None and time.time() < deadline:
        time.sleep(poll_interval)


def _wait_for_assignment_or_error(link, poll_interval=0.02):  # pragma: no cover
    """Block until the network thread has recorded either a seat (color()
    becomes non-None, from the server's `assigned` message) or a refusal
    (error() becomes non-None, from the server's `error` message) --
    whichever the server sends first; the two are mutually exclusive on the
    wire. Polling a plain lock-guarded field matches how the rest of
    _ServerLink is read (snapshot()/color() are read the same way, not via
    a condition variable). Called before cv2.namedWindow, so an `error`
    never gets a window opened for it -- see client.composition.run().

    Called after the room choice (protocol.PLAY/ROOM_CREATE/ROOM_JOIN) has
    already been sent -- see run() -- so this window, unlike
    _wait_for_login_error above, has no fixed bound: the server may itself
    be waiting on a slow human at the OTHER end of a room dialog (see
    server.rooms._ROOM_MESSAGE_TIMEOUT_S), and there is nothing more useful
    for this end to do than keep waiting for that same human's own
    verdict.

    Also covers a room request (slide 6) with no separate condition of its
    own: the server always sends `room` strictly before `assigned` on a
    successful room_create/room_join (see server.connection._handle_client),
    so by the time this returns ready, room() is already populated
    whenever a room was requested at all -- a room refusal arrives as
    `error`, same as every other refusal this function already waits on."""
    while link.color() is None and link.error() is None:
        time.sleep(poll_interval)
