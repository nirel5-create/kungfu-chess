"""A real OS dialog (tkinter) for the Home screen: logging in, then
choosing Create/Join a room, Play (find any match), or Quit.

The third button is labelled Play rather than "Cancel": this dialog
reappears after every game, and "Cancel" reads as "abort" rather than
"find me an opponent", though the behaviour is the same either way -- no
room message sent, and the server places the player in the shared game
or matches them by rating.

Every dialog builds on ONE persistent, hidden tk.Tk() root, created on
first use and reused for the process's life, shown modally as a
tk.Toplevel via root.wait_window() rather than its own mainloop() --
Tcl only cleanly supports one interpreter per process, and cycling
many tk.Tk() instances through create-run-destroy eventually crashes
it. This module owns the dialogs, not what a caller does with the choice.
"""

import time
import tkinter as tk
from tkinter import messagebox

from common.matchmaker import SEARCH_TIMEOUT_MS
from common.validation import MAX_NAME_LENGTH, is_displayable

CREATE = "create"
JOIN = "join"
PLAY = "play"
QUIT = "quit"

_root = None  # pylint: disable=invalid-name
# Mutable module state (reassigned by _get_root/shutdown via `global`),
# not a constant -- pylint's naming check cannot tell the difference for
# a module-level name, only UPPER_CASE vs. not. The one Tk interpreter
# for the whole process -- see _get_root()'s own docstring.


def _get_root():  # pragma: no cover -- opens a real window
    """-> the single, persistent, hidden Tk root every dialog in this
    module builds under, created on first use and reused for the rest
    of the process's life."""
    global _root  # pylint: disable=global-statement
    if _root is None:
        _root = tk.Tk()
        _root.withdraw()  # this root is never shown itself -- only its Toplevels are
    return _root


def shutdown():  # pragma: no cover -- opens a real window
    """Destroy the persistent root, if one was ever created this
    session. Called once, right before the client exits for good. A
    no-op if no dialog was ever shown, so callers never need to guard
    the call themselves."""
    global _root  # pylint: disable=global-statement
    if _root is not None:
        _root.destroy()
        _root = None


def normalize_room_name(text):
    """-> `text` stripped of surrounding whitespace, or "" if that
    leaves nothing usable. Kept separate from ask_room so it can be
    tested without opening a real window."""
    return text.strip()


def ask_room(title="Home", username=None, rating=None):  # pragma: no cover -- opens a real window
    """Show the Home screen: a room-name entry plus Create/Join/Play/Quit.
    -> (action, room_name), with room_name "" for Play, Quit, or the
    window's own close (treated as Quit: this dialog reappears after
    every game, so closing it almost certainly means "done"). An empty
    or invalid Create/Join name re-shows the problem in place."""
    result = [QUIT, ""]
    root = _get_root()
    dialog = tk.Toplevel(root)
    dialog.title(title)

    if username is not None and rating is not None:
        tk.Label(dialog, text=f"Logged in as {username} (rating {rating})").pack(
            padx=10, pady=(10, 0))

    tk.Label(dialog, text="room name").pack(padx=10, pady=(10, 0))
    entry = tk.Entry(dialog)
    entry.pack(padx=10, pady=5)
    entry.focus_set()

    def choose(action):
        if action in (PLAY, QUIT):
            result[0] = action
        else:
            name = normalize_room_name(entry.get())
            if not name:
                return  # empty box: stay open rather than send nothing
            if not is_displayable(name):
                messagebox.showerror(
                    "Room",
                    "Room names may only use letters, digits, spaces, "
                    f"- and _, up to {MAX_NAME_LENGTH} characters.",
                    parent=dialog)
                return  # stay open so the player can fix it
            result[0] = action
            result[1] = name
        dialog.destroy()

    buttons = tk.Frame(dialog)
    buttons.pack(padx=10, pady=(0, 10))
    tk.Button(buttons, text="Create", command=lambda: choose(CREATE)).pack(
        side=tk.LEFT, padx=5)
    tk.Button(buttons, text="Join", command=lambda: choose(JOIN)).pack(
        side=tk.LEFT, padx=5)
    tk.Button(buttons, text="Play", command=lambda: choose(PLAY)).pack(
        side=tk.LEFT, padx=5)
    tk.Button(buttons, text="Quit", command=lambda: choose(QUIT)).pack(
        side=tk.LEFT, padx=5)

    # The window's own close button gets the same treatment as Quit --
    # see this function's own docstring.
    dialog.protocol("WM_DELETE_WINDOW", lambda: choose(QUIT))

    dialog.grab_set()
    root.wait_window(dialog)
    return tuple(result)


def show_no_opponent_found():  # pragma: no cover -- opens a real window
    """Tell the player Play's search found no opponent, via a real OS
    dialog rather than console text or an OpenCV overlay -- matchmaking
    runs entirely before any game window exists."""
    messagebox.showinfo("Play", "No opponent found. Try again later.", parent=_get_root())


_PROGRESS_POLL_MS = 200  # how often the countdown label is refreshed


def _outcome_known(link):
    """-> whether `link` already has a result to report: a seat, a
    matchmaking status of "found" or "timeout", or an error. Shared by
    show_matchmaking_progress's up-front check and its poll, so both
    agree on what counts as resolved."""
    return (link.matchmaking_status() in ("found", "timeout")
            or link.color() is not None or link.error() is not None)


def show_matchmaking_progress(link):  # pragma: no cover -- opens a real window
    """Show Play's search live, with a countdown. Closes itself the
    moment `link` reports an outcome, or does nothing if one is already
    known. Schedules its first poll via dialog.after(0, tick) instead of
    calling tick() directly, which could destroy the window before
    wait_window() is watching it, raising TclError."""
    if _outcome_known(link):
        return
    root = _get_root()
    dialog = tk.Toplevel(root)
    dialog.title("Play")
    tk.Label(dialog, text="Searching for an opponent...").pack(padx=30, pady=(20, 5))
    seconds_label = tk.Label(dialog, text="")
    seconds_label.pack(padx=30, pady=(0, 20))

    started_at = time.monotonic()

    def tick():
        if _outcome_known(link):
            if dialog.winfo_exists():  # idempotent: the window's own
                #   close button, if clicked mid-search, already
                #   destroys it independently of this poll.
                dialog.destroy()
            return
        remaining_ms = max(0, SEARCH_TIMEOUT_MS - int((time.monotonic() - started_at) * 1000))
        seconds_label.config(text=f"{remaining_ms // 1000}s left")
        dialog.after(_PROGRESS_POLL_MS, tick)

    dialog.after(0, tick)
    root.wait_window(dialog)
