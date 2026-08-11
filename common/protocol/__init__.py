"""The single source of truth for the wire format. Nothing else in client
or server may build or parse a message by hand.

Split by subject: core.py owns type names, the required-field table and
JSON framing; snapshot.py owns GameSnapshot/CaptureEntry <-> dict
conversion; messages.py owns one builder per message type, built on both.
Every name below is re-exported here so `from common import protocol` and
`protocol.move(...)` keep working exactly as before the split.
"""

from common.protocol.core import (
    ASSIGNED, COUNTDOWN, ERROR, GAME_OVER, HISTORY, JUMP, LOGIN, MATCHMAKING,
    MOVE, PLAY, RATING, ROOM, ROOM_CREATE, ROOM_JOIN, STATE, WAITING,
    CaptureEntry, ProtocolError, dumps, loads,
)
from common.protocol.messages import (
    assigned, countdown, error, game_over, history, jump, login, matchmaking,
    move, play, rating, room, room_create, room_join, state, waiting,
)
from common.protocol.snapshot import decode_capture_log, decode_snapshot, encode_snapshot

__all__ = [
    "ASSIGNED", "COUNTDOWN", "ERROR", "GAME_OVER", "HISTORY", "JUMP", "LOGIN",
    "MATCHMAKING", "MOVE", "PLAY", "RATING", "ROOM", "ROOM_CREATE", "ROOM_JOIN",
    "STATE", "WAITING", "CaptureEntry", "ProtocolError", "dumps", "loads",
    "assigned", "countdown", "error", "game_over", "history", "jump", "login",
    "matchmaking", "move", "play", "rating", "room", "room_create", "room_join",
    "state", "waiting", "decode_capture_log", "decode_snapshot", "encode_snapshot",
]
