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


def _piece(kind, color, row, col, state="idle"):
    return PieceView(kind=kind, color=color, row=row, col=col,
                      x=float(col), y=float(row), state=state, rest_progress=0.0)


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


def test_a_pawn_arriving_promoted_at_a_new_cell_publishes_sound_promotion():
    # The real engine promotes a pawn AT ITS DESTINATION cell, so cell and
    # kind change together in one transition -- there is no snapshot pair
    # where the SAME cell shows both the old and the new kind. This is the
    # scenario that was silently never firing before the fix.
    bus = Bus()
    rec = _Recorder(bus)
    source = GameEventSource(bus)
    source.on_snapshot(_snap([_piece("P", "w", 1, 0)]))
    source.on_snapshot(_snap([_piece("Q", "w", 0, 0)]))
    assert rec.received[topics.SOUND] == [{"name": "promotion"}]


def test_promotion_uses_the_injected_promotions_mapping_not_a_hardcoded_one():
    bus = Bus()
    rec = _Recorder(bus)
    source = GameEventSource(bus, promotions={"wN": "wB"})  # an unusual variant
    source.on_snapshot(_snap([_piece("N", "w", 1, 0)]))
    source.on_snapshot(_snap([_piece("B", "w", 0, 0)]))
    assert rec.received[topics.SOUND] == [{"name": "promotion"}]


def test_promotion_takes_precedence_over_move():
    bus = Bus()
    rec = _Recorder(bus)
    source = GameEventSource(bus)
    # An unrelated piece also moves in the same frame as the promotion.
    source.on_snapshot(_snap([_piece("P", "w", 1, 0), _piece("R", "w", 5, 5)]))
    source.on_snapshot(_snap([_piece("Q", "w", 0, 0), _piece("R", "w", 5, 6)]))
    assert rec.received[topics.SOUND] == [{"name": "promotion"}]


def test_promotion_takes_precedence_over_capture_when_a_promoting_pawn_captures_on_arrival():
    bus = Bus()
    rec = _Recorder(bus)
    source = GameEventSource(bus)
    source.on_snapshot(_snap([_piece("P", "w", 1, 0), _piece("R", "b", 0, 0)]))
    source.on_snapshot(_snap([_piece("Q", "w", 0, 0)]))  # captured the rook, promoted
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


def test_a_piece_transitioning_into_jumping_publishes_sound_jump():
    # A jump never changes cell -- only state (see model.snapshot's
    # STATE_JUMPING) -- so this is the scenario a cell-based detector
    # like _moved/_captured is structurally blind to.
    bus = Bus()
    rec = _Recorder(bus)
    source = GameEventSource(bus)
    source.on_snapshot(_snap([_piece("R", "w", 0, 0)]))
    source.on_snapshot(_snap([_piece("R", "w", 0, 0, state="jumping")]))
    assert rec.received[topics.SOUND] == [{"name": "jump"}]
    # A jump does not move or capture anything, so neither of those fires.
    assert rec.received[topics.MOVE_LOG] == []
    assert rec.received[topics.SCORE_UPDATE] == []


def test_jumping_state_persisting_over_several_snapshots_publishes_jump_once():
    bus = Bus()
    rec = _Recorder(bus)
    source = GameEventSource(bus)
    source.on_snapshot(_snap([_piece("R", "w", 0, 0)]))
    source.on_snapshot(_snap([_piece("R", "w", 0, 0, state="jumping")]))
    source.on_snapshot(_snap([_piece("R", "w", 0, 0, state="jumping")]))
    source.on_snapshot(_snap([_piece("R", "w", 0, 0, state="jumping")]))
    assert rec.received[topics.SOUND] == [{"name": "jump"}]


def test_a_frame_with_a_jump_and_an_unrelated_move_publishes_only_move():
    # Pieces act independently in real time, so a jump on one piece can
    # land in the same frame as an unrelated piece's move -- the move is
    # the more informative of the two (see on_snapshot's precedence).
    bus = Bus()
    rec = _Recorder(bus)
    source = GameEventSource(bus)
    source.on_snapshot(_snap([_piece("R", "w", 0, 0), _piece("N", "w", 2, 2)]))
    source.on_snapshot(_snap(
        [_piece("R", "w", 0, 0, state="jumping"), _piece("N", "w", 2, 1)]))
    assert rec.received[topics.SOUND] == [{"name": "move"}]


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
