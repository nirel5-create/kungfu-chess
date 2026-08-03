"""A real OS dialog for choosing a room (slide 6): "Button: Room -> open a
windows message with text box and buttons: Create / Join / Cancel."

There is no Home screen in this project: login is a terminal prompt (slide
3) and the window then opens straight into the game. So this dialog is
shown where a Home screen would have been -- after the username prompt and
before the OpenCV window opens -- rather than as a screen of its own. That
is a considered placement to fit this project's shape, not an oversight.

The third button is labelled Play, not the slide's own "Cancel": a player
testing this had no way to know "Cancel" meant "skip the room and find me
an opponent" -- the word says "abort", not "match me". Slide 5 already
names that action Play, so this dialog borrows that name instead of
inventing a third word for the same idea. The behaviour is exactly what
"Cancel" described: no room message is sent, and the server puts the
player in the ordinary shared game (see server.py's _find_or_create_game).
Real ELO-based matchmaking is slide 5 and is NOT implemented by this
button or anywhere else in this step -- Play is simply the entry point
that future work will attach it to, unchanged from here.

tkinter ships with Python, so this needs no new dependency. The slide
explicitly rules out a hand-drawn OpenCV dialog -- a text box painted
inside the game window would mean handling keyboard events and drawing
characters by hand, more work than this needs -- so a real window is used
instead.

What this module owns: the dialog itself, and normalizing what it returns.
What it does NOT own: what CREATE/JOIN/PLAY do afterward -- that is
client.py's job; this only reports the player's choice.
"""

import tkinter as tk
from tkinter import messagebox

CREATE = "create"
JOIN = "join"
PLAY = "play"


def normalize_room_name(text):
    """-> `text` stripped of surrounding whitespace, or "" if that leaves
    nothing usable (e.g. an all-whitespace or empty string). The one pure,
    decidable piece of this dialog -- kept separate from ask_room so it can
    be tested without opening a real window."""
    return text.strip()


def ask_room(title="Room"):  # pragma: no cover -- opens a real window
    """Show a small window with a "room name" text box and three buttons --
    Create, Join, Play (see this module's docstring for why the slide's own
    "Cancel" is not used).

    -> (action, room_name). `action` is CREATE, JOIN or PLAY. `room_name`
    is "" whenever action is PLAY -- for the Play button, for the window's
    own close ("X"), and also for Create/Join pressed with an empty (or
    whitespace-only) box, which is treated the same as Play rather than
    sent on: a blank name must never reach the server. On a non-empty
    Create/Join, `room_name` is normalize_room_name's result."""
    result = [PLAY, ""]
    root = tk.Tk()
    root.title(title)

    tk.Label(root, text="room name").pack(padx=10, pady=(10, 0))
    entry = tk.Entry(root)
    entry.pack(padx=10, pady=5)
    entry.focus_set()

    def choose(action):
        if action != PLAY:
            name = normalize_room_name(entry.get())
            if not name:
                return  # empty box: stay open rather than send nothing
            result[0] = action
            result[1] = name
        root.destroy()

    buttons = tk.Frame(root)
    buttons.pack(padx=10, pady=(0, 10))
    tk.Button(buttons, text="Create", command=lambda: choose(CREATE)).pack(
        side=tk.LEFT, padx=5)
    tk.Button(buttons, text="Join", command=lambda: choose(JOIN)).pack(
        side=tk.LEFT, padx=5)
    tk.Button(buttons, text="Play", command=lambda: choose(PLAY)).pack(
        side=tk.LEFT, padx=5)

    # The window's own close button gets the same treatment as Play --
    # see this function's own docstring.
    root.protocol("WM_DELETE_WINDOW", lambda: choose(PLAY))

    root.mainloop()
    return tuple(result)


def show_no_opponent_found():  # pragma: no cover -- opens a real window
    """Show a message box saying Play's search found no opponent (slide 5:
    "pops up a message that can't find") -- a real OS dialog, the same
    tkinter approach ask_room already uses, not console text and not
    something drawn in the OpenCV window (there is no window at this
    point: matchmaking runs entirely before one ever opens -- see
    client.py's run()). tkinter.messagebox rather than hand-built widgets
    like ask_room's, since this needs nothing more than an acknowledgement
    -- there is no choice for the player to make here."""
    root = tk.Tk()
    root.withdraw()  # nothing else needs this window; only the messagebox does
    messagebox.showinfo("Play", "No opponent found. Try again later.")
    root.destroy()
