"""Bus topic names, in one place, so a typo is impossible and the full event
vocabulary is readable at a glance (mirrors how ERROR_* codes live in one
module elsewhere in this codebase).
"""

SNAPSHOT = "snapshot"          # a new GameSnapshot arrived
SCORE_UPDATE = "score_update"  # Slide 1a
MOVE_LOG = "move_log"          # Slide 1b
SOUND = "sound"                # Slide 1c
GAME_START = "game_start"      # Slide 1d
GAME_END = "game_end"          # Slide 1d
COUNTDOWN = "countdown"        # disconnect countdown
MATCHMAKING = "matchmaking"    # Play button status
ROOM = "room"                  # room created / joined
CONNECTION = "connection"      # connected / disconnected
