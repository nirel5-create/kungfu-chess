"""A real OS dialog for choosing a room (slide 6): "Button: Room -> open a
windows message with text box and buttons: Create / Join / Cancel." Step 12
(slide 3) extends it into the project's Home screen: a fourth button (Quit)
and a line showing who is logged in, shown once right after login and again
every time a game ends -- see client/homescreen.py's HomeFlow for the loop
this sits inside, and client.py's run() for the plumbing that drives it.

The third button is labelled Play, not the slide's own "Cancel": a player
testing this had no way to know "Cancel" meant "skip the room and find me
an opponent" -- the word says "abort", not "match me". Slide 5 already
names that action Play, so this dialog borrows that name instead of
inventing a third word for the same idea. The behaviour is exactly what
"Cancel" described: no room message is sent, and the server either puts the
player in the ordinary shared game or, if they hold no seat anywhere
already, finds them a real match by rating (slide 5.1, common.matchmaker).

tkinter ships with Python, so this needs no new dependency. The slide
explicitly rules out a hand-drawn OpenCV dialog -- a text box painted
inside the game window would mean handling keyboard events and drawing
characters by hand, more work than this needs -- so a real window is used
instead.

What this module owns: the dialog itself, and normalizing what it returns.
What it does NOT own: what CREATE/JOIN/PLAY/QUIT do afterward -- that is
client.py's job; this only reports the player's choice.

show_matchmaking_progress (live-testing fix) is the one exception to "this
only reports the player's choice": Play used to close this dialog and
leave the player watching nothing but a terminal line while the server
searched for up to a minute, with no visible sign anything was happening.
This shows that search live instead, in its own small window, polling the
already-open connection (client.py's _ServerLink) directly rather than
being handed a finished result the way ask_room's own callers are.

Every dialog here is built on ONE persistent, hidden tk.Tk() root
(_get_root), created the first time any of them is shown and destroyed
exactly once, by client.py's run(), when the whole client is about to
exit (shutdown) -- not a fresh tk.Tk() per dialog, which is what this
module used to do. Tcl only cleanly supports one interpreter lifetime per
process: cycling many tk.Tk() instances through create-run-destroy in the
same process eventually crashes ("Tcl_AsyncDelete: async handler deleted
by the wrong thread") -- a bug live testing found on Play's SECOND search
within one session, once enough dialogs (the Home screen shown after
every game, plus this module's own matchmaking-progress window) had
cycled through. Every dialog is instead a tk.Toplevel of that one root,
shown modally with root.wait_window(dialog) instead of dialog.mainloop(),
so the root's own single Tcl event loop is what actually processes every
button click and root.after callback -- never a second, competing
interpreter, and never anything but the ONE thread that calls client.py's
run() in the first place (the network thread, _ServerLink's own, never
imports this module or touches a Tk object at all -- see
show_matchmaking_progress's own docstring for the plain, lock-guarded
values it reads instead)."""

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
    module builds its window under, creating it the first time any
    dialog is shown and reusing the same one for the rest of the
    process's life -- see this module's own docstring for why."""
    global _root  # pylint: disable=global-statement
    if _root is None:
        _root = tk.Tk()
        _root.withdraw()  # this root is never shown itself -- only its Toplevels are
    return _root


def shutdown():  # pragma: no cover -- opens a real window
    """Destroy the persistent root, if this session ever created one --
    called once, by client.py's run(), right before it returns for good
    (Quit chosen, a refusal, the window closed -- every ending). A no-op
    if no dialog was ever shown this session, so callers never need to
    guard the call themselves."""
    global _root  # pylint: disable=global-statement
    if _root is not None:
        _root.destroy()
        _root = None


def normalize_room_name(text):
    """-> `text` stripped of surrounding whitespace, or "" if that leaves
    nothing usable (e.g. an all-whitespace or empty string). The one pure,
    decidable piece of this dialog -- kept separate from ask_room so it can
    be tested without opening a real window."""
    return text.strip()


def ask_room(title="Home", username=None, rating=None):  # pragma: no cover -- opens a real window
    """Show the Home screen (slide 3, Step 12): a "room name" text box and
    four buttons -- Create, Join, Play, Quit (see this module's docstring
    for why the slide's own "Cancel" is named Play here).

    -> (action, room_name). `action` is CREATE, JOIN, PLAY or QUIT.
    `room_name` is "" whenever action is PLAY or QUIT -- for those two
    buttons, for the window's own close ("X", treated the same as Quit:
    this dialog is shown again after every game (Step 12), so closing it
    almost certainly means "I am done", not "match me with someone" --
    unlike the old one-shot Room dialog this replaces, where Play was the
    more likely reason to close it) -- and also for Create/Join pressed
    with an empty (or whitespace-only) box, which stays open rather than
    sending nothing: a blank name must never reach the server. On a
    non-empty Create/Join, `room_name` is normalize_room_name's result.

    username/rating, when both given, are shown in a label line --
    "Logged in as alice (rating 1187)" -- so the player can see who they
    are and, the next time this dialog appears, that their rating
    changed. Shown as plain room-choosing UI with neither, e.g. for a
    caller with nothing to report yet.

    A name is_displayable rejects (Step 11: emoji and most other Unicode
    have no glyph in cv2's built-in font, and would show as boxes or
    garbage in the room indicator) shows the problem right here, in a
    message box over this same still-open window, rather than being sent
    on for the server to refuse -- there is no reason to make a round
    trip to find out something this window can already tell.

    Built as a tk.Toplevel of the one persistent root (_get_root), shown
    modally with root.wait_window(dialog) rather than its own
    dialog.mainloop() -- see this module's own docstring for why a fresh
    tk.Tk() per call (what this used to do) is not safe to keep doing
    call after call, game after game."""
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
    """Show a message box saying Play's search found no opponent (slide 5:
    "pops up a message that can't find") -- a real OS dialog, the same
    tkinter approach ask_room already uses, not console text and not
    something drawn in the OpenCV window (there is no window at this
    point: matchmaking runs entirely before one ever opens -- see
    client.py's run()). tkinter.messagebox rather than hand-built widgets
    like ask_room's, since this needs nothing more than an acknowledgement
    -- there is no choice for the player to make here.

    Parented to the one persistent root (_get_root) -- see this module's
    own docstring -- rather than a throwaway tk.Tk() of its own."""
    messagebox.showinfo("Play", "No opponent found. Try again later.", parent=_get_root())


_PROGRESS_POLL_MS = 200  # how often the countdown label is refreshed


def _outcome_known(link):
    """-> whether `link` already has a result to report: a seat
    (`color()`), a matchmaking status of "found" or "timeout", or a
    refusal (`error()`). Shared by show_matchmaking_progress's own
    up-front check and its tick() poll, so the two can never drift
    apart -- what counts as "resolved" is decided in exactly one
    place."""
    return (link.matchmaking_status() in ("found", "timeout")
            or link.color() is not None or link.error() is not None)


def show_matchmaking_progress(link):  # pragma: no cover -- opens a real window
    """Show Play's search (slide 5.1) as it happens, counting down the
    minute it is allowed to run, instead of just closing the Home dialog
    and leaving the player looking at nothing but a terminal line (the
    bug this fixes -- found by live testing). Closes itself the moment
    `link` reports an outcome: a seat (`color()`), a matchmaking status
    of "found" or "timeout", or a refusal (`error()`). show_no_opponent_
    found still runs separately, after this closes, on a timeout --
    unchanged; this only covers the WAITING part slide 5's own message
    box never did.

    -> immediately, with no window ever built, if `link` already has an
    outcome before this is even called -- the common case when Play is
    chosen while an opponent is already queued: matching can resolve
    faster than this function is entered. There is nothing to show for a
    search that is already over, and building a window only to tear it
    straight back down is exactly the race that used to crash this (see
    below).

    Call this right after sending protocol.play() on `link` -- already
    open, already logged in (see client.py's run()). Polls `link` via
    dialog.after, not a background thread of its own: every poll and
    every button click across this whole module runs on the ONE Tcl
    event loop the persistent root owns (_get_root, root.wait_window
    below) -- the same thread that calls client.py's run() in the first
    place. What `link.matchmaking_status()`/`color()`/`error()` return
    here are plain values (a string or None) a lock already guards on
    the _ServerLink side, read fresh on every poll -- never a Tk widget,
    and never anything the network thread itself touches: that thread
    has no reason to import this module at all, and does not.

    A returning player whose held seat is still theirs (Step 12) never
    shows "searching" at all: `color()` becoming non-None on the very
    first poll closes this immediately, the same "no explicit found
    needed" reasoning client.py's own matchmaking wait already
    documents.

    tick()'s own first run is SCHEDULED (dialog.after(0, tick)), never
    called directly, and root.wait_window(dialog) is started right after
    scheduling it, not before: an after() callback only ever fires once
    Tk's event loop is actually pumping, which wait_window is what
    starts, so this ordering guarantees the first poll cannot run --
    and so cannot destroy `dialog` -- before wait_window is already
    watching it. Calling tick() directly before wait_window (what this
    used to do) raced it instead: a result that resolved in the moment
    between building the window and that direct call destroyed `dialog`
    on the spot, and wait_window then crashed (TclError: bad window path
    name) trying to wait on a window already gone -- reliably, since
    Play against an opponent already queued resolves this fast almost
    every time, not as a rare edge case."""
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
