"""The single source of truth for the wire format, exactly as `boardio` is the
single source of truth for the text format. Nothing else in client or server
may build or parse a message by hand.

What protocol owns: message type names, message construction, JSON
encode/decode, and GameSnapshot <-> dict conversion.
What protocol does NOT own: sockets, game rules, sessions, or when to send.

Full-snapshot decision: the server sends the COMPLETE board state every tick,
never deltas. Every message is therefore the whole truth, so client and
server cannot drift, a reconnecting client resyncs with no special logic, and
a viewer joining mid-game just receives the current state. Bandwidth is
irrelevant for a local two-player server, and deltas would buy nothing while
adding exactly the synchronisation complexity we are trying to avoid.

Cells are [row, col] lists, not [x, y] and not a notation string. The
engine's command surface (request_move(src, dst)) already speaks in cells, so
sending cells means zero translation on either side. The slide's WQe2e5 is
illustrative; if it is ever wanted on screen, add format_move_notation() here
and nowhere else.
"""

import json

from model.position import Position
from model.snapshot import GameSnapshot, PieceView

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
ROOM = "room"
ERROR = "error"

# Colors are "w" / "b" -- the same spelling Config and PieceView already
# use. Do not introduce "white" / "black" anywhere.

# type -> field names a message of that type must carry.
_REQUIRED_FIELDS = {
    LOGIN: ("username",),
    MOVE: ("src", "dst"),
    JUMP: ("cell",),
    PLAY: (),
    ROOM_CREATE: ("name",),
    ROOM_JOIN: ("id",),
    STATE: ("snapshot",),
    ASSIGNED: ("color",),
    COUNTDOWN: ("seconds",),
    GAME_OVER: ("winner",),
    MATCHMAKING: ("status",),
    ROOM: ("id",),
    ERROR: ("reason",),
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


# --- framing --------------------------------------------------------------

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


# --- builders: client -> server --------------------------------------------

def login(username):
    """`username` is the free-text name the player typed at the client's shell
    prompt before the window opened (slide 3: login in a shell, not the GUI).
    Sent once, as the very first message on a new connection -- before any
    `move`/`jump` -- so the server can log which username took which color.
    There is no password and no persistence here: this is presentation only
    (slide 3); the account system is a later step. The client only checks
    non-emptiness before sending, so `username` is never `""`, but the server
    does not re-validate it -- a malformed or missing `username` fails at
    `loads()`, same as any other required field."""
    return {"type": LOGIN, "username": username}


def move(src, dst):
    """`src` and `dst` are each a `(row, col)` pair identifying the piece's current
    cell and the cell it is being sent to. Both are coerced to two-element lists,
    so callers may pass a `Position`, a tuple, or any other indexable pair. The
    server hands both straight to `request_move(src, dst)` -- it does not itself
    check that the move is legal; that is the engine's job."""
    return {"type": MOVE, "src": [src[0], src[1]], "dst": [dst[0], dst[1]]}


def jump(cell):
    """`cell` is a `(row, col)` pair naming the cell of the piece that jumps -- its
    OWN current cell, not a destination. A jump does not move the piece: it stays on
    its logical square and only re-arms (its cooldown/state changes). There is no
    source/target pair because nothing travels. The server hands `cell` to
    `request_jump(cell)`, which locates the piece sitting there and jumps it."""
    return {"type": JUMP, "cell": [cell[0], cell[1]]}


def play():
    """Carries no payload beyond its type. Tells the server this client wants to
    be entered into matchmaking; the server replies with `matchmaking` messages
    as the search progresses."""
    return {"type": PLAY}


def room_create(name):
    """`name` is the human-readable room name chosen by the creator, sent as-is
    with no validation or normalization. The server is free to reject an empty or
    duplicate name by replying with `error` rather than `room`."""
    return {"type": ROOM_CREATE, "name": name}


def room_join(room_id):
    """`room_id` is the room's id, which is also its human-readable name -- the same
    string the creator chose and the value shown at the top of the screen (per the
    slides, the room id is essentially the room name). The server may reply with
    `room` on success, or `error` if no such room exists."""
    return {"type": ROOM_JOIN, "id": room_id}


# --- builders: server -> client ---------------------------------------------

def state(snapshot):
    """`snapshot` is a `GameSnapshot`, encoded here into the full board state via
    `encode_snapshot`. Per the full-snapshot decision, every `state` message is the
    complete truth, never a delta: the receiver may simply replace whatever it had
    before, with no merge logic and no risk of drifting out of sync, whether it is
    the original client, a reconnecting one, or a viewer joining mid-game."""
    return {"type": STATE, "snapshot": encode_snapshot(snapshot)}


def assigned(color):
    """`color` is one of `"w"`, `"b"`, or `"viewer"` -- never `"white"`/`"black"`.
    Sent once when a client is seated, it tells the receiver which side (if any) it
    is allowed to send `move`/`jump` commands for; `"viewer"` may only watch."""
    return {"type": ASSIGNED, "color": color}


def countdown(seconds):
    """`seconds` is the whole number of seconds remaining before the server acts
    on a disconnect (e.g. forfeits the game on behalf of the missing player). The
    receiver should treat each message as the current remaining count, not a
    decrement, since a reconnect can cancel or reset the countdown at any time."""
    return {"type": COUNTDOWN, "seconds": seconds}


def game_over(winner, rating=None):
    """`winner` is `"w"`, `"b"`, or `None` for a draw. `rating`, when present, is
    this client's own result: `{"you": <new rating>, "delta": <signed change>}`,
    where `delta` is the ELO adjustment the server has ALREADY applied and persisted
    (so `you == old + delta`). It is `None` when there is no rating to report. Once
    sent, the game is finished; the receiver should stop accepting further moves."""
    return {"type": GAME_OVER, "winner": winner, "rating": rating}


def matchmaking(status):
    """`status` is one of `"searching"`, `"found"`, or `"timeout"`, describing the
    outcome of a prior `play` request. `"found"` means a game is about to start
    (an `assigned` message follows); `"timeout"` means the search gave up and the
    client must send `play` again to retry."""
    return {"type": MATCHMAKING, "status": status}


def room(room_id):
    """`room_id` is the room's id, sent in reply to `room_create` or `room_join`.
    It doubles as the room's name and is written at the top of the client's screen
    so a player can read it out and invite someone to `room_join` the same id."""
    return {"type": ROOM, "id": room_id}


def error(reason):
    """`reason` is a short human-readable string describing what went wrong, not a
    machine-readable code (unlike `ProtocolError.code`). It is meant for logging or
    display, not for the receiver to branch on."""
    return {"type": ERROR, "reason": reason}


# --- snapshot conversion -----------------------------------------------------

def encode_snapshot(snapshot):
    """GameSnapshot -> dict of JSON-safe primitives."""
    selected = snapshot.selected_cell
    return {
        "board_width": snapshot.board_width,
        "board_height": snapshot.board_height,
        "cell_size": snapshot.cell_size,
        "pieces": [_encode_piece(piece) for piece in snapshot.pieces],
        "selected_cell": [selected.row, selected.col] if selected is not None else None,
        "game_over": snapshot.game_over,
        "board_offset": list(snapshot.board_offset),
    }


def _encode_piece(piece):
    return {
        "kind": piece.kind, "color": piece.color, "row": piece.row, "col": piece.col,
        "x": piece.x, "y": piece.y, "state": piece.state,
        "rest_progress": piece.rest_progress,
    }


def decode_snapshot(data):
    """dict -> GameSnapshot. Rebuilds the two traps JSON introduces: `pieces`
    comes back as a tuple of PieceView (not a list of list), and
    `board_offset` comes back as a tuple (not a list), so equality with a
    snapshot built by the engine holds field for field.

    Any structurally bad input -- not a dict, a missing field, or a malformed
    `selected_cell`/`board_offset` -- raises ProtocolError(BAD_PAYLOAD) rather
    than a raw KeyError/TypeError, upholding this module's promise that bad
    input never crashes the server."""
    if not isinstance(data, dict):
        raise ProtocolError(ProtocolError.BAD_PAYLOAD)
    try:
        selected = data["selected_cell"]
        return GameSnapshot(
            board_width=data["board_width"],
            board_height=data["board_height"],
            cell_size=data["cell_size"],
            pieces=tuple(_decode_piece(piece) for piece in data["pieces"]),
            selected_cell=_decode_cell(selected) if selected is not None else None,
            game_over=data["game_over"],
            board_offset=_decode_offset(data["board_offset"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProtocolError(ProtocolError.BAD_PAYLOAD) from exc


def _decode_cell(value):
    if not (isinstance(value, (list, tuple)) and len(value) == 2):
        raise ProtocolError(ProtocolError.BAD_PAYLOAD)
    return Position(value[0], value[1])


def _decode_offset(value):
    if not (isinstance(value, (list, tuple)) and len(value) == 2):
        raise ProtocolError(ProtocolError.BAD_PAYLOAD)
    return tuple(value)


def _decode_piece(data):
    return PieceView(
        kind=data["kind"], color=data["color"], row=data["row"], col=data["col"],
        x=data["x"], y=data["y"], state=data["state"],
        rest_progress=data["rest_progress"],
    )
