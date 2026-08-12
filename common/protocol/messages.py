"""One builder per message type -- the only place a message's shape is
written down. Nothing else in client or server may build one by hand.

Full-snapshot decision: the server sends the COMPLETE board state every
tick, never deltas. Every `state`/`history` message is therefore the whole
truth, so client and server cannot drift, a reconnecting client resyncs
with no special logic, and a viewer joining mid-game just receives the
current state. Bandwidth is irrelevant for a local two-player server, and
deltas would buy nothing while adding exactly the synchronisation
complexity this avoids.

Cells are [row, col] lists, not [x, y] and not a notation string. The
engine's command surface (request_move(src, dst)) already speaks in cells,
so sending cells means zero translation on either side.
"""

from common.protocol.core import (
    ASSIGNED, COUNTDOWN, ERROR, GAME_OVER, HISTORY, JUMP, LOGIN, MATCHMAKING,
    MOVE, PLAY, RATING, ROOM, ROOM_CREATE, ROOM_JOIN, STATE, WAITING,
)
from common.protocol.snapshot import encode_capture_entry, encode_snapshot

# --- builders: client -> server --------------------------------------------


def login(username, password=""):
    """`username` is the free-text name the player typed at the client's
    shell prompt before the window opened. Sent once, as the first
    message on a new connection. `password` is sent as typed, in the
    clear, over this local WebSocket -- a real deployment would need
    TLS (wss://) first. Never stored: hashed (common/db.py) on arrival."""
    return {"type": LOGIN, "username": username, "password": password}


def move(src, dst):
    """`src` and `dst` are each a `(row, col)` pair identifying the piece's
    current cell and the cell it is being sent to. Both are coerced to
    two-element lists, so callers may pass a `Position`, a tuple, or any
    other indexable pair. The receiving server does not itself check that
    the move is legal; that is the engine's job."""
    return {"type": MOVE, "src": [src[0], src[1]], "dst": [dst[0], dst[1]]}


def jump(cell):
    """`cell` is a `(row, col)` pair naming the OWN current cell of the piece
    that jumps, not a destination -- a jump re-arms a piece in place rather
    than moving it, so there is no source/target pair."""
    return {"type": JUMP, "cell": [cell[0], cell[1]]}


def play():
    """Carries no payload beyond its type. Tells the server this client wants
    to be entered into matchmaking; the server replies with `matchmaking`
    messages as the search progresses."""
    return {"type": PLAY}


def room_create(name):
    """`name` is the human-readable room name chosen by the creator, sent
    as-is with no validation or normalization. The server is free to reject
    an empty or duplicate name by replying with `error` rather than `room`."""
    return {"type": ROOM_CREATE, "name": name}


def room_join(room_id):
    """`room_id` is the room's id, which is also its human-readable name --
    the string the creator chose and the value shown at the top of the
    screen. The server may reply with `room` on success, or `error` if no
    such room exists."""
    return {"type": ROOM_JOIN, "id": room_id}


# --- builders: server -> client ---------------------------------------------


def state(snapshot):
    """`snapshot` is a `GameSnapshot`, encoded here into the full board
    state -- the complete truth, never a delta."""
    return {"type": STATE, "snapshot": encode_snapshot(snapshot)}


def assigned(color):
    """`color` is one of `"w"`, `"b"`, or `"viewer"` -- never
    `"white"`/`"black"`. Tells the receiver which side (if any) it may send
    `move`/`jump` commands for; `"viewer"` may only watch."""
    return {"type": ASSIGNED, "color": color}


def countdown(seconds):
    """`seconds` is the whole number of seconds remaining before the server
    acts on a disconnect. The receiver should treat each message as the
    current remaining count, not a decrement: a reconnect can cancel or
    reset the countdown at any time."""
    return {"type": COUNTDOWN, "seconds": seconds}


def game_over(winner, winner_username=None, rating=None):
    # pylint: disable=redefined-outer-name
    # `rating` is this function's own parameter, unrelated to the
    # module-level rating() builder below.
    """`winner` is "w", "b", or None -- no draw: an inconclusive game
    reports None, not scored either. `winner_username` is the display
    name for a decisive win, resolved by the server from the game's
    seats. `rating`, when present, is `{"you": <new rating>, "delta":
    <signed change>}`, already applied and persisted."""
    return {"type": GAME_OVER, "winner": winner,
            "winner_username": winner_username, "rating": rating}


def matchmaking(status):
    """`status` is one of `"searching"`, `"found"`, or `"timeout"`,
    describing the outcome of a prior `play` request. `"found"` means a
    game is about to start (an `assigned` message follows); `"timeout"`
    means the search gave up and the client must send `play` again to
    retry."""
    return {"type": MATCHMAKING, "status": status}


def history(white_name, black_name, white_score, black_score, log):
    """The current move log, scores, and display names for a game, sent
    whenever any of them changes and once when a connection joins or
    reconnects, computed once by the server's own CaptureLog so every
    client watching sees the same thing. white_name/black_name default
    to "Player 1"/"Player 2"; `log` is sent in FULL, oldest first, never a delta."""
    return {
        "type": HISTORY,
        "white_name": white_name,
        "black_name": black_name,
        "white_score": white_score,
        "black_score": black_score,
        "log": [encode_capture_entry(entry) for entry in log],
    }


def rating(value):
    """`value` is this connection's OWN current ELO rating, shown in the
    home dialog so the player can see who they are and, on a later game,
    that it changed. Sent once, right after a successful login, and again
    whenever a game this connection was seated in ends decisively and
    updates it -- there is no request message for this, only the push."""
    return {"type": RATING, "rating": value}


def room(room_id):
    """`room_id` is the room's id, sent in reply to `room_create` or
    `room_join`. It doubles as the room's name and is written at the top of
    the client's screen so a player can read it out and invite someone to
    `room_join` the same id."""
    return {"type": ROOM, "id": room_id}


def error(reason):
    """`reason` is a short, stable string describing what went wrong, not
    a machine-readable code (unlike `ProtocolError.code`). Mostly for
    logging/display, but the client does branch on ROOM_REFUSAL_REASONS
    and IDLE_TIMEOUT -- see client.composition.run."""
    return {"type": ERROR, "reason": reason}


def waiting(is_waiting):
    """`is_waiting` is whether this game currently has an empty "w" or
    "b" seat: without it, a solo player could walk a piece across an
    unopposed board and capture the empty side's king for a free,
    repeatable win. Sent whenever this value CHANGES, so a client can
    show "Waiting for an opponent" for exactly as long as it is true."""
    return {"type": WAITING, "waiting": is_waiting}
