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
    asked for. Shared by server.connection._run_game_loop (an immediate
    send when a connection joins or reconnects) and server.tick (the
    ongoing send-on-change broadcast), so whichever runs first for a
    given game_id is the one that actually creates it; the other just
    reuses it."""
    observer = observers.get(game_id)
    if observer is None:
        observer = CaptureLog(CONFIG)
        observers[game_id] = observer
    return observer


def _seat_names(seats):  # pragma: no cover
    """-> (white_name, black_name): the CURRENT username seated at each
    color, or "Player 1"/"Player 2" for a seat nobody has taken yet.

    Computed fresh from `seats` (GameRegistry.seats(game_id)) every time:
    CaptureLog (see its own module docstring) has no concept of names at
    all, precisely because a name can change -- a seat gets taken --
    after a game already has one, and a game can easily already have a
    CaptureLog (created on its very first tick, before anyone has joined)
    by the time its second seat is taken. This is what lets a placeholder
    become a real name the moment that seat is taken."""
    white = next((user for user, color in seats.items() if color == "w"), None)
    black = next((user for user, color in seats.items() if color == "b"), None)
    return white or "Player 1", black or "Player 2"


async def _send_history(websocket, observers, registry, game_id):  # pragma: no cover
    """Send `game_id`'s current move log, scores and names to `websocket`
    -- used for an immediate send when a connection joins or reconnects
    (server.connection._run_game_loop), so it is never left showing an
    empty panel just because it was not there for the captures that
    already happened -- a viewer joining mid-game gets this too, for the
    same reason and at no extra cost. server.tick's own send-on-change
    broadcast builds the same message itself, for potentially many
    recipients at once, rather than calling this once per recipient."""
    observer = _observer_for(observers, game_id)
    white_name, black_name = _seat_names(registry.seats(game_id))
    message = dumps(build_history_message(
        white_name, black_name, observer.score_of("w"), observer.score_of("b"), observer.log()))
    await websocket.send(message)
