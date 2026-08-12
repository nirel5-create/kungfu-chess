"""Async WebSocket server for Kung-Fu Chess.

Every ~30 ms this advances every live game and broadcasts each game's
state to the clients sitting in it; a client's `move`/`jump` message is
decoded and handed to GameSession.submit, never built or applied here.

Owns the websocket connections, the tick interval, and broadcasting --
not which games exist, seats, or lifecycle (common.registry.
GameRegistry), nor game rules or command handling (common.net.
GameSession). Not unit-tested itself: a live socket cannot be driven
from a test without becoming an integration test.

Split by subject: session.py, auth.py, rooms.py, matchmaking.py,
history.py, connection.py, tick.py, ratings.py, composition.py (the
composition root). Names below are re-exported for existing imports.
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
