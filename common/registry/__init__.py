"""Registry of live games: which exist, who sits in which seat, and what
happens to a game once it ends. Split by subject: game.py owns the small
per-game data holder and the duplicate-connection error; registry.py owns
GameRegistry itself. Both are re-exported here so `from common.registry
import GameRegistry, AlreadyConnectedError` keeps working exactly as before
the split.
"""

from common.registry.game import AlreadyConnectedError
from common.registry.registry import DISCONNECT_GRACE_MS, GAME_END_LINGER_MS, GameRegistry

__all__ = ["AlreadyConnectedError", "DISCONNECT_GRACE_MS", "GAME_END_LINGER_MS", "GameRegistry"]
