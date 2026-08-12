"""A shared validator for anything that eventually gets drawn on screen with
cv2.putText: usernames and room names. Both the server (a client is not
trusted) and client/roomdialog.py (so a player can fix a bad name before it
is ever sent) call is_displayable, which REJECTS a bad name rather than
rewriting it -- unlike common.logsetup.sanitize_for_filename, which exists
for a name the player never sees.
"""

import re

# Long enough for a real name or a real room name, short enough that it
# cannot overflow the score panel (view/score_panel.py, frozen, a fixed-
# width strip) or the room indicator drawn above it -- picked by eye
# against real rendered frames, the same way client.py's own _PANEL_WIDTH
# was.
MAX_NAME_LENGTH = 20

# Letters, digits, spaces, "-" and "_" only -- every one of these has a
# glyph in cv2's built-in font. Inner spaces are kept deliberately: this
# is checked against the STRIPPED name, so a leading/trailing space never
# reaches here, but a name like "my room" still matches in full.
_ALLOWED = re.compile(r"^[A-Za-z0-9 _-]+$")


def is_displayable(name):
    """-> whether `name` is safe to draw with cv2.putText: non-empty and
    no longer than MAX_NAME_LENGTH once stripped, made up only of
    letters, digits, spaces, "-" and "_" (other Unicode has no glyph in
    cv2's built-in font and renders as boxes). Rejects rather than
    rewrites: a name the player typed is theirs to fix, not ours to mangle."""
    stripped = name.strip()
    if not stripped or len(stripped) > MAX_NAME_LENGTH:
        return False
    return bool(_ALLOWED.fullmatch(stripped))
