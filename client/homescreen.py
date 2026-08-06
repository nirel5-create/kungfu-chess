"""The client's own state machine for what screen the player is on (slide
3's Home screen, Step 12): LOGIN (no username yet) -> HOME (logged in,
choosing what to do) -> PLAYING (in a game) -> back to HOME once it ends,
in a loop; QUIT is reached only from HOME.

No window, no socket -- deciding "what happens after a game ends" (does
the player go back to LOGIN, or stay HOME?) is exactly the kind of
decision that must be unit-tested the same way common.matchmaker.
MatchMaker and common.registry.GameRegistry already are (see their own
module docstrings): the decision is pure, the window/socket plumbing that
drives it (client.py's run()) is pragma: no cover.
"""

LOGIN = "login"
HOME = "home"
PLAYING = "playing"
QUIT = "quit"


class HomeFlow:
    """A fresh flow starts at LOGIN, with no username and no room name."""

    def __init__(self):
        self._state = LOGIN
        self._username = None
        self._room_name = ""

    @property
    def state(self):
        """-> the current state: LOGIN, HOME, PLAYING, or QUIT."""
        return self._state

    @property
    def username(self):
        """-> the logged-in username, or None before logged_in() has ever
        succeeded (or after login_refused() -- see its own docstring)."""
        return self._username

    @property
    def room_name(self):
        """-> the room name remembered from the most recent chose() call,
        or "" -- both before any choice has been made, and again once
        game_ended() has cleared it (see its own docstring)."""
        return self._room_name

    def logged_in(self, username):
        """The server accepted this login (no refusal arrived) -- LOGIN
        -> HOME, remembering `username` for the rest of the session (a
        client never logs in again after this)."""
        self._username = username
        self._state = HOME

    def login_refused(self, reason):  # pylint: disable=unused-argument
        """The server refused this login attempt -- back to LOGIN, with
        no stale username: whatever was typed did not work, so it must
        not linger as if it had. `reason` is kept only for a caller that
        wants to display it; this class does not branch on it."""
        self._username = None
        self._state = LOGIN

    def chose(self, action, room_name=""):
        """The player picked `action` at HOME (client.roomdialog.CREATE/
        JOIN/PLAY/QUIT). CREATE/JOIN/PLAY all move to PLAYING, remembering
        `room_name` for as long as PLAYING lasts (readable via the
        room_name property) -- "" for PLAY, the same as ask_room already
        returns for it. QUIT moves to the terminal QUIT state instead,
        and never touches `room_name`."""
        if action == QUIT:
            self._state = QUIT
            return
        self._room_name = room_name
        self._state = PLAYING

    def game_ended(self):
        """The game that was PLAYING has ended -- back to HOME, NOT
        LOGIN: a player who has already logged in stays logged in and is
        never asked to log in again. Clears the remembered room name, so
        the next chose() starts from "" rather than showing a stale room
        from the game that just ended."""
        self._room_name = ""
        self._state = HOME
