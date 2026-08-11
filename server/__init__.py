"""Async WebSocket server for Kung-Fu Chess.

app.py's local frame loop is clock.tick() -> engine.snapshot() ->
renderer.render(). The server keeps the first half of that loop -- the
clock and the engine -- and moves the second half to whichever clients are
connected: every ~30 ms it advances every live game and broadcasts each
game's state to the clients sitting in that game, so each window redraws
the same board as the others in its game. Commands travel the other way: a
client sends a `move`/`jump` message, decoded and handed to
GameSession.submit -- nothing here builds or applies a command itself.

What this package owns: the websocket connections, the tick interval, and
broadcasting. What it does NOT own: which games exist, seats, or lifecycle
-- that is common.registry.GameRegistry; nor game rules or command handling
-- that is common.net.GameSession, one layer below the registry. This
package is plumbing only, and is not unit-tested, the same way app.py's
real OpenCV window is not: a live socket cannot be driven from a test
without becoming an integration test. GameRegistry and GameSession are
fully covered by tests/unit/test_registry.py and tests/unit/test_session.py.

Split by subject: session.py (how a fresh game is built), auth.py (login),
rooms.py (Room and the default shared game), matchmaking.py (Play),
history.py (per-game move history), connection.py (one connection's whole
lifetime), tick.py (the per-tick broadcast loop), ratings.py (the two
places this touches Postgres directly), composition.py (the composition
root `main()` that wires all of the above and starts listening -- not
named app.py, to avoid colliding with the root app.py's own coverage
config, see .coveragerc's omit list). The handful of
names below are re-exported so existing imports of the module -- `from
server import _create_room`, and so on -- keep working exactly as before
the split.
"""

from server.auth import _reserve_username
from server.rooms import _create_room, _find_or_create_game, _join_room
from server.ratings import _update_ratings_on_game_end
from server.tick import _winner_username

# composition (and, through it, connection) is not otherwise reached by
# anything `import server` already pulls in above -- only the root
# server.py shim imports it, and that shim is itself never imported under
# test (it is a pragma: no cover entry point). Importing it here too is
# what lets its own module-level code (imports, constants -- everything
# outside `# pragma: no cover` functions) be exercised the same way every
# other submodule's is, by the ordinary `import server` this package's
# own tests already do, rather than needing a dedicated test of its own
# for code that is not itself logic.
from server import composition  # noqa: F401  pylint: disable=unused-import

__all__ = [
    "_create_room", "_find_or_create_game", "_join_room", "_reserve_username",
    "_update_ratings_on_game_end", "_winner_username",
]
