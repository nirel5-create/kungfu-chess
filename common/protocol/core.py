"""Message type names, the required-field table that drives validation, and
the JSON framing (dumps/loads) every message goes through. The rest of the
`protocol` package -- message builders in messages.py, GameSnapshot
encode/decode in snapshot.py -- both depend on this module; this module
depends on neither of them.
"""

import json
from collections import namedtuple

# view.observer.CaptureEntry has this exact shape (capturer_color,
# victim_token, cost, clock_ms), and importing it directly was tried first
# -- but it broke the server in Docker: view/ is the client's OpenCV
# rendering stack and is deliberately not copied into the server image
# (see Dockerfile), so `from view.observer import CaptureEntry` raised
# ModuleNotFoundError at startup, every time, in the container only (the
# unit suite never catches this, since view/ exists on the host). view/
# observer.py is also frozen and cannot be changed to import this
# definition from common/ instead. So this is protocol's own wire-level
# equivalent -- common/ must depend on nothing above it, exactly as
# common/db.py, common/registry.py and the rest of this package already
# do. Never compared to or constructed from a real view.observer.
# CaptureEntry: namedtuple equality is by value, not by class, and every
# reader of a decoded log (client.panel_overlay.PanelOverlay, view/
# score_panel.py's frozen ScorePanel) only ever reads these same four
# fields by name, so a matching value works identically regardless of
# which of the two classes produced it.
CaptureEntry = namedtuple("CaptureEntry", "capturer_color victim_token cost clock_ms")

# --- message type names -------------------------------------------------

# client -> server
LOGIN = "login"
MOVE = "move"
JUMP = "jump"
PLAY = "play"
ROOM_CREATE = "room_create"
ROOM_JOIN = "room_join"

# server -> client
STATE = "state"
ASSIGNED = "assigned"
COUNTDOWN = "countdown"
GAME_OVER = "game_over"
MATCHMAKING = "matchmaking"
HISTORY = "history"
RATING = "rating"
ROOM = "room"
ERROR = "error"
WAITING = "waiting"

# Colors are "w" / "b" -- the same spelling Config and PieceView already
# use. Do not introduce "white" / "black" anywhere.

# type -> field names a message of that type must carry.
_REQUIRED_FIELDS = {
    LOGIN: ("username", "password"),
    MOVE: ("src", "dst"),
    JUMP: ("cell",),
    PLAY: (),
    ROOM_CREATE: ("name",),
    ROOM_JOIN: ("id",),
    STATE: ("snapshot",),
    ASSIGNED: ("color",),
    COUNTDOWN: ("seconds",),
    GAME_OVER: ("winner", "winner_username"),
    MATCHMAKING: ("status",),
    HISTORY: ("white_name", "black_name", "white_score", "black_score", "log"),
    RATING: ("rating",),
    ROOM: ("id",),
    ERROR: ("reason",),
    WAITING: ("waiting",),
}

# type -> subset of its required fields that must be a [row, col] cell.
_CELL_FIELDS = {
    MOVE: ("src", "dst"),
    JUMP: ("cell",),
}


class ProtocolError(Exception):
    """Raised when a message cannot be turned into a dict, or a dict is not a
    valid message. Carries a stable, machine-readable code -- mirrors
    BoardParseError -- so callers can map it to their own `error` message."""

    MALFORMED_JSON = "MALFORMED_JSON"
    NOT_AN_OBJECT = "NOT_AN_OBJECT"        # valid JSON but not a dict
    MISSING_TYPE = "MISSING_TYPE"
    UNKNOWN_TYPE = "UNKNOWN_TYPE"
    BAD_PAYLOAD = "BAD_PAYLOAD"            # right type, wrong/missing fields

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def dumps(message):
    """dict -> wire text."""
    return json.dumps(message)


def loads(text):
    """Wire text -> dict. Raises ProtocolError with a stable code so the
    server never crashes because a client sent rubbish."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ProtocolError(ProtocolError.MALFORMED_JSON) from exc
    if not isinstance(data, dict):
        raise ProtocolError(ProtocolError.NOT_AN_OBJECT)
    if "type" not in data:
        raise ProtocolError(ProtocolError.MISSING_TYPE)
    message_type = data["type"]
    if message_type not in _REQUIRED_FIELDS:
        raise ProtocolError(ProtocolError.UNKNOWN_TYPE)
    for field in _REQUIRED_FIELDS[message_type]:
        if field not in data:
            raise ProtocolError(ProtocolError.BAD_PAYLOAD)
    for field in _CELL_FIELDS.get(message_type, ()):
        _validate_cell(data[field])
    return data


def _validate_cell(value):
    is_cell = (
        isinstance(value, list) and len(value) == 2
        and all(isinstance(v, int) and not isinstance(v, bool) for v in value)
    )
    if not is_cell:
        raise ProtocolError(ProtocolError.BAD_PAYLOAD)
