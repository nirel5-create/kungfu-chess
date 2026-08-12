"""Per-game move history: the server's own CaptureLog for each game, and
sending its current log/scores/names to a client -- either the immediate
send a joining or reconnecting connection needs (_send_history, below), or
the ongoing send-on-change broadcast server.tick drives for every connected
client at once.
"""

from common.capture_log import CaptureLog
from common.protocol import history as build_history_message
from common.protocol import dumps
from server.session import CONFIG


def _observer_for(observers, game_id):  # pragma: no cover
    """-> the CaptureLog for `game_id`, creating one the first time it is
    asked for. Shared by the immediate join/reconnect send and the
    ongoing tick broadcast, so whichever runs first for a game_id creates
    it and the other just reuses it."""
    observer = observers.get(game_id)
    if observer is None:
        observer = CaptureLog(CONFIG)
        observers[game_id] = observer
    return observer


def _seat_names(seats):  # pragma: no cover
    """-> (white_name, black_name): the current username at each color, or
    "Player 1"/"Player 2" for a seat nobody has taken yet. Computed fresh
    from `seats` every time, since CaptureLog itself has no concept of
    names -- a seat can be taken after its CaptureLog already exists."""
    white = next((user for user, color in seats.items() if color == "w"), None)
    black = next((user for user, color in seats.items() if color == "b"), None)
    return white or "Player 1", black or "Player 2"


async def _send_history(websocket, observers, registry, game_id):  # pragma: no cover
    """Send `game_id`'s current move log, scores and names to `websocket`
    -- the immediate per-connection send used when joining or
    reconnecting, so nobody sees an empty panel just because they missed
    earlier captures. server.tick's own broadcast builds the same message
    once for many recipients instead of calling this per recipient."""
    observer = _observer_for(observers, game_id)
    white_name, black_name = _seat_names(registry.seats(game_id))
    message = dumps(build_history_message(
        white_name, black_name, observer.score_of("w"), observer.score_of("b"), observer.log()))
    await websocket.send(message)
