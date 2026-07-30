import pytest

from common import protocol, topics
from common.bus import Bus
from common.net import GameSession
from common.registry import GAME_END_LINGER_MS, AlreadyConnectedError, GameRegistry
from engine.game import GameEngine
from model.board import Board
from tests.helpers import CFG, wait_for


class _FakeSession:
    """A minimal stand-in for GameSession, for registry tests that are not
    about game-over -- avoids building a real board when nothing here
    inspects piece positions or snapshots."""

    def __init__(self):
        self.game_over = False
        self.advanced_ms = []

    def advance(self, ms):
        self.advanced_ms.append(ms)


def _capturing_session():
    """A white king and rook beside a black king, so a single 1-cell rook
    move captures the black king while white's own king remains on the
    board. Both kings must exist for the winner-derivation logic to mean
    anything: capturing black's king while white also has none on the board
    would leave zero kings, not one, and "no winner" is a different case
    from "white wins". Used as `make_session` where a test needs a real
    game-over, not a fake."""
    board = Board([["wK", "wR", "bK"]], CFG)
    return GameSession(GameEngine(board, CFG))


# --- create -------------------------------------------------------------

def test_create_returns_an_id_and_game_ids_contains_it():
    registry = GameRegistry(_FakeSession)
    game_id = registry.create()
    assert game_id in registry.game_ids()


def test_create_with_an_explicit_game_id_uses_that_exact_id():
    registry = GameRegistry(_FakeSession)
    game_id = registry.create(game_id="cocorico")
    assert game_id == "cocorico"
    assert "cocorico" in registry.game_ids()


def test_create_with_a_duplicate_id_raises_value_error():
    registry = GameRegistry(_FakeSession)
    registry.create(game_id="cocorico")
    with pytest.raises(ValueError):
        registry.create(game_id="cocorico")


# --- join / leave / color_of ---------------------------------------------

def test_first_join_gets_w_second_b_third_and_fourth_get_viewer():
    registry = GameRegistry(_FakeSession)
    game_id = registry.create()
    assert registry.join(game_id, "alice") == "w"
    assert registry.join(game_id, "bob") == "b"
    assert registry.join(game_id, "carol") == "viewer"
    assert registry.join(game_id, "dave") == "viewer"


def test_join_with_a_username_that_already_has_a_seat_and_has_left_returns_the_same_color():
    # "already has a seat" alone is not enough to call this a reconnect --
    # see the two tests below for the case this used to get wrong.
    registry = GameRegistry(_FakeSession)
    game_id = registry.create()
    first = registry.join(game_id, "alice")
    registry.leave(game_id, "alice")
    again = registry.join(game_id, "alice")
    assert again == first


def test_a_second_join_while_the_username_is_still_connected_raises():
    # The bug this fixes: the same username opening a second window (no
    # leave() in between) used to get the SAME seat back, letting both
    # windows control the same pieces. `connected` is what tells "coming
    # back" apart from "still here". A prior fix silently seated the
    # second connection as "viewer" instead, which stopped the double
    # control but left the player with no explanation for why their
    # window suddenly could not move anything -- an explicit, named
    # exception is what lets the caller (server.py) tell them why: a
    # refusal the player can read beats a silent demotion they must
    # deduce.
    registry = GameRegistry(_FakeSession)
    game_id = registry.create()
    first = registry.join(game_id, "alice")
    assert first == "w"
    with pytest.raises(AlreadyConnectedError):
        registry.join(game_id, "alice")  # no leave() -- still connected


def test_a_duplicate_connection_attempt_does_not_disturb_the_original_seat():
    registry = GameRegistry(_FakeSession)
    game_id = registry.create()
    registry.join(game_id, "alice")
    with pytest.raises(AlreadyConnectedError):
        registry.join(game_id, "alice")  # duplicate -> raises, but must
        #                                   not overwrite alice's real seat
    assert registry.color_of(game_id, "alice") == "w"


def test_leave_then_join_with_the_same_username_returns_the_same_color_again():
    registry = GameRegistry(_FakeSession)
    game_id = registry.create()
    color = registry.join(game_id, "alice")
    registry.leave(game_id, "alice")
    assert registry.join(game_id, "alice") == color


def test_leave_then_join_with_a_different_username_does_not_get_the_vacated_color():
    registry = GameRegistry(_FakeSession)
    game_id = registry.create()
    registry.join(game_id, "alice")  # takes "w"
    registry.leave(game_id, "alice")
    assert registry.join(game_id, "bob") == "b"


def test_leave_on_an_unknown_game_or_unknown_username_does_not_raise():
    registry = GameRegistry(_FakeSession)
    registry.leave("no-such-game", "alice")
    game_id = registry.create()
    registry.leave(game_id, "nobody-joined")


def test_join_on_an_unknown_game_raises_key_error():
    registry = GameRegistry(_FakeSession)
    with pytest.raises(KeyError):
        registry.join("no-such-game", "alice")


def test_color_of_returns_the_seat_and_none_for_a_stranger():
    registry = GameRegistry(_FakeSession)
    game_id = registry.create()
    registry.join(game_id, "alice")
    assert registry.color_of(game_id, "alice") == "w"
    assert registry.color_of(game_id, "stranger") is None


def test_session_of_an_unknown_id_returns_none():
    registry = GameRegistry(_FakeSession)
    assert registry.session("no-such-game") is None


def test_color_of_returns_none_for_an_unknown_game():
    registry = GameRegistry(_FakeSession)
    assert registry.color_of("no-such-game", "alice") is None


# --- advance --------------------------------------------------------------

def test_advance_ticks_every_game_both_progress():
    registry = GameRegistry(_FakeSession)
    id_a = registry.create()
    id_b = registry.create()
    registry.advance(30)
    assert registry.session(id_a).advanced_ms == [30]
    assert registry.session(id_b).advanced_ms == [30]


# --- game-over lifecycle ---------------------------------------------------

def test_on_king_capture_game_end_is_published_once_with_winner_and_seats():
    bus = Bus()
    published = []
    bus.subscribe(topics.GAME_END, published.append)
    registry = GameRegistry(_capturing_session, bus=bus)
    game_id = registry.create()
    registry.join(game_id, "alice")  # "w"
    registry.join(game_id, "bob")    # "b"

    session = registry.session(game_id)
    session.submit(protocol.move((0, 1), (0, 2)))
    registry.advance(wait_for(1))

    assert len(published) == 1
    payload = published[0]
    assert payload["game_id"] == game_id
    assert payload["winner"] == "w"
    assert payload["seats"] == {"alice": "w", "bob": "b"}


def test_game_end_is_not_published_a_second_time_on_further_advance_calls():
    bus = Bus()
    published = []
    bus.subscribe(topics.GAME_END, published.append)
    registry = GameRegistry(_capturing_session, bus=bus)
    game_id = registry.create()

    session = registry.session(game_id)
    session.submit(protocol.move((0, 1), (0, 2)))
    registry.advance(wait_for(1))
    count_after_first_end = len(published)

    registry.advance(100)
    registry.advance(100)
    assert len(published) == count_after_first_end


def test_a_finished_game_is_still_present_before_the_linger_period_elapses():
    registry = GameRegistry(_capturing_session)
    game_id = registry.create()
    session = registry.session(game_id)
    session.submit(protocol.move((0, 1), (0, 2)))
    capture_ms = wait_for(1)
    registry.advance(capture_ms)  # ends the game; this tick's ms already
    #                               counts toward the linger period
    assert registry.session(game_id) is not None

    registry.advance(GAME_END_LINGER_MS - capture_ms - 1)
    assert registry.session(game_id) is not None
    assert game_id in registry.game_ids()


def test_a_finished_game_is_gone_after_the_linger_period_elapses():
    registry = GameRegistry(_capturing_session)
    game_id = registry.create()
    session = registry.session(game_id)
    session.submit(protocol.move((0, 1), (0, 2)))
    capture_ms = wait_for(1)
    registry.advance(capture_ms)

    registry.advance(GAME_END_LINGER_MS - capture_ms)
    assert registry.session(game_id) is None
    assert game_id not in registry.game_ids()


def test_winner_is_none_when_no_piece_matches_the_registrys_king_type():
    # king_type="Z" matches no piece on the board, so _winner_of finds zero
    # kings rather than exactly one -- the other branch of "the winner is
    # None" from the docstring (0 found, not 2).
    bus = Bus()
    published = []
    bus.subscribe(topics.GAME_END, published.append)
    registry = GameRegistry(_capturing_session, bus=bus, king_type="Z")
    game_id = registry.create()

    session = registry.session(game_id)
    session.submit(protocol.move((0, 1), (0, 2)))
    registry.advance(wait_for(1))

    assert published[0]["winner"] is None


def test_game_start_is_published_on_create():
    bus = Bus()
    published = []
    bus.subscribe(topics.GAME_START, published.append)
    registry = GameRegistry(_FakeSession, bus=bus)
    game_id = registry.create()
    assert published == [{"game_id": game_id}]


def test_with_bus_none_nothing_raises_and_lifecycle_still_works():
    registry = GameRegistry(_FakeSession, bus=None)
    game_id = registry.create()
    assert registry.join(game_id, "alice") == "w"
    registry.advance(100)
    assert registry.session(game_id) is not None
