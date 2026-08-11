"""GameSnapshot <-> dict conversion, and the same for a capture log entry
(CaptureEntry, core.py) -- the two structured payloads message builders in
messages.py embed rather than build inline.
"""

from model.position import Position
from model.snapshot import GameSnapshot, PieceView

from common.protocol.core import CaptureEntry, ProtocolError


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


def encode_capture_entry(entry):
    """CaptureEntry -> dict of JSON-safe primitives, one entry of history's
    own `log` list."""
    return {
        "capturer_color": entry.capturer_color,
        "victim_token": entry.victim_token,
        "cost": entry.cost,
        "clock_ms": entry.clock_ms,
    }


def decode_capture_log(data):
    """list of encoded entries (see messages.history's own docstring) ->
    tuple of CaptureEntry, oldest first. Raises ProtocolError(BAD_PAYLOAD)
    on anything malformed, the same promise decode_snapshot already keeps
    for its own field."""
    try:
        return tuple(
            CaptureEntry(capturer_color=item["capturer_color"],
                         victim_token=item["victim_token"],
                         cost=item["cost"], clock_ms=item["clock_ms"])
            for item in data
        )
    except (KeyError, TypeError) as exc:
        raise ProtocolError(ProtocolError.BAD_PAYLOAD) from exc
