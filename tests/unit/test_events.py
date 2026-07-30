from client.events import GameEventSource
from common import topics
from common.bus import Bus
from engine.game import GameEngine
from model.board import Board
from model.snapshot import GameSnapshot, PieceView
from tests.helpers import CFG

_TOPICS = (topics.GAME_START, topics.SOUND, topics.MOVE_LOG,
           topics.SCORE_UPDATE, topics.GAME_END)


class _Recorder:
    """Subscribes to every topic GameEventSource can publish and records
    the payloads, per topic -- a real Bus, not a mock of one."""

    def __init__(self, bus):
        self.received = {topic: [] for topic in _TOPICS}
        for topic in _TOPICS:
            bus.subscribe(topic, self._handler(topic))

    def _handler(self, topic):
        return lambda payload: self.received[topic].append(payload)


def _piece(kind, color, row, col):
    return PieceView(kind=kind, color=color, row=row, col=col,
                      x=float(col), y=float(row), state="idle", rest_progress=0.0)


def _snap(pieces, game_over=False):
    return GameSnapshot(board_width=3, board_height=3, cell_size=100,
                         pieces=tuple(pieces), selected_cell=None,
                         game_over=game_over, board_offset=(0, 0))


def test_the_first_snapshot_publishes_game_start_and_nothing_else():
    bus = Bus()
    rec = _Recorder(bus)
    source = GameEventSource(bus)
    source.on_snapshot(_snap([_piece("R", "w", 0, 0)]))
    assert rec.received[topics.GAME_START] == [{}]
    assert rec.received[topics.SOUND] == []
    assert rec.received[topics.MOVE_LOG] == []
    assert rec.received[topics.SCORE_UPDATE] == []
    assert rec.received[topics.GAME_END] == []


def test_an_identical_second_snapshot_publishes_no_sound_at_all():
    bus = Bus()
    rec = _Recorder(bus)
    source = GameEventSource(bus)
    source.on_snapshot(_snap([_piece("R", "w", 0, 0)]))
    source.on_snapshot(_snap([_piece("R", "w", 0, 0)]))
    assert rec.received[topics.SOUND] == []
    assert rec.received[topics.MOVE_LOG] == []


def test_a_piece_changing_cell_publishes_sound_move_once():
    bus = Bus()
    rec = _Recorder(bus)
    source = GameEventSource(bus)
    source.on_snapshot(_snap([_piece("R", "w", 0, 0)]))
    source.on_snapshot(_snap([_piece("R", "w", 0, 1)]))
    assert rec.received[topics.SOUND] == [{"name": "move"}]
    assert rec.received[topics.MOVE_LOG] == [{}]


def test_the_same_move_still_in_progress_over_three_snapshots_publishes_move_once():
    # A real engine, not hand-built snapshots: the piece's logical cell only
    # flips once, on arrival, even though the move spans many ticks -- this
    # is the transition test, the important one.
    board = Board([["wR", ".", "."]], CFG)
    engine = GameEngine(board, CFG)
    bus = Bus()
    rec = _Recorder(bus)
    source = GameEventSource(bus)

    source.on_snapshot(engine.snapshot())  # 1st ever: GAME_START only
    engine.request_move((0, 0), (0, 2))    # 2 cells -> 2000ms total
    engine.wait(500)
    source.on_snapshot(engine.snapshot())  # mid-flight
    engine.wait(500)
    source.on_snapshot(engine.snapshot())  # still mid-flight (1000/2000)
    engine.wait(500)
    source.on_snapshot(engine.snapshot())  # still mid-flight (1500/2000)
    engine.wait(600)                       # past 2000ms -> arrived
    source.on_snapshot(engine.snapshot())  # arrival

    assert rec.received[topics.SOUND] == [{"name": "move"}]
    assert rec.received[topics.MOVE_LOG] == [{}]


def test_a_piece_vanishing_publishes_sound_capture():
    bus = Bus()
    rec = _Recorder(bus)
    source = GameEventSource(bus)
    source.on_snapshot(_snap([_piece("R", "w", 0, 0), _piece("K", "b", 0, 2)]))
    source.on_snapshot(_snap([_piece("R", "w", 0, 2)]))
    assert rec.received[topics.SOUND] == [{"name": "capture"}]


def test_a_capture_also_publishes_score_update():
    bus = Bus()
    rec = _Recorder(bus)
    source = GameEventSource(bus)
    source.on_snapshot(_snap([_piece("R", "w", 0, 0), _piece("K", "b", 0, 2)]))
    source.on_snapshot(_snap([_piece("R", "w", 0, 2)]))
    assert rec.received[topics.SCORE_UPDATE] == [{}]


def test_a_piece_changing_kind_at_the_same_cell_publishes_sound_promotion():
    bus = Bus()
    rec = _Recorder(bus)
    source = GameEventSource(bus)
    source.on_snapshot(_snap([_piece("P", "w", 0, 0)]))
    source.on_snapshot(_snap([_piece("Q", "w", 0, 0)]))
    assert rec.received[topics.SOUND] == [{"name": "promotion"}]


def test_game_over_flipping_publishes_sound_game_over_and_game_end():
    bus = Bus()
    rec = _Recorder(bus)
    source = GameEventSource(bus)
    source.on_snapshot(_snap(
        [_piece("K", "w", 0, 0), _piece("K", "b", 0, 2)], game_over=False))
    source.on_snapshot(_snap([_piece("K", "w", 0, 2)], game_over=True))
    assert rec.received[topics.SOUND] == [{"name": "game_over"}]
    assert rec.received[topics.GAME_END] == [{}]


def test_game_over_staying_true_does_not_publish_game_end_again():
    bus = Bus()
    rec = _Recorder(bus)
    source = GameEventSource(bus)
    source.on_snapshot(_snap(
        [_piece("K", "w", 0, 0), _piece("K", "b", 0, 2)], game_over=False))
    source.on_snapshot(_snap([_piece("K", "w", 0, 2)], game_over=True))
    source.on_snapshot(_snap([_piece("K", "w", 0, 2)], game_over=True))
    assert len(rec.received[topics.GAME_END]) == 1


def test_game_start_is_published_only_once_even_after_many_snapshots():
    bus = Bus()
    rec = _Recorder(bus)
    source = GameEventSource(bus)
    for i in range(5):
        source.on_snapshot(_snap([_piece("R", "w", 0, i)]))
    assert len(rec.received[topics.GAME_START]) == 1


def test_a_frame_with_both_a_capture_and_a_move_publishes_only_capture():
    bus = Bus()
    rec = _Recorder(bus)
    source = GameEventSource(bus)
    # Two white rooks and a black king. In one frame: the first rook moves
    # to an empty cell (a move), and the second rook captures the king (a
    # capture) -- both in the same snapshot transition.
    source.on_snapshot(_snap([
        _piece("R", "w", 0, 0), _piece("R", "w", 1, 0), _piece("K", "b", 1, 2),
    ]))
    source.on_snapshot(_snap([
        _piece("R", "w", 0, 1),
        _piece("R", "w", 1, 2),
    ]))
    assert rec.received[topics.SOUND] == [{"name": "capture"}]
