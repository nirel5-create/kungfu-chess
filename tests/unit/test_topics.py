from common import topics


def test_each_topic_constant_is_its_own_lowercase_snake_case_name():
    assert topics.SNAPSHOT == "snapshot"
    assert topics.SCORE_UPDATE == "score_update"
    assert topics.MOVE_LOG == "move_log"
    assert topics.SOUND == "sound"
    assert topics.GAME_START == "game_start"
    assert topics.GAME_END == "game_end"
    assert topics.COUNTDOWN == "countdown"
    assert topics.MATCHMAKING == "matchmaking"
    assert topics.ROOM == "room"
    assert topics.CONNECTION == "connection"


def test_every_topic_constant_is_unique():
    values = [
        topics.SNAPSHOT, topics.SCORE_UPDATE, topics.MOVE_LOG, topics.SOUND,
        topics.GAME_START, topics.GAME_END, topics.COUNTDOWN,
        topics.MATCHMAKING, topics.ROOM, topics.CONNECTION,
    ]
    assert len(values) == len(set(values))
