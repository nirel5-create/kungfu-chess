import pytest

from common import protocol, topics
from common.bus import Bus
from common.net import GameSession
from common.registry import (
    DISCONNECT_GRACE_MS, GAME_END_LINGER_MS, AlreadyConnectedError, GameRegistry,
)
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

    def force_game_over(self):
        """Real GameSession.force_game_over's stand-in (Step 9's
        auto-resign calls this unconditionally) -- game_over is a plain
        attribute here, not a property, so setting it directly is enough."""
        self.game_over = True


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


def test_seats_returns_the_current_seat_map_including_viewers():
    registry = GameRegistry(_FakeSession)
    game_id = registry.create()
    registry.join(game_id, "alice")
    registry.join(game_id, "bob")
    registry.join(game_id, "carol")  # viewer
    assert registry.seats(game_id) == {"alice": "w", "bob": "b", "carol": "viewer"}


def test_seats_on_an_unknown_game_returns_an_empty_mapping():
    registry = GameRegistry(_FakeSession)
    assert registry.seats("no-such-game") == {}


def test_color_of_returns_none_for_an_unknown_game():
    registry = GameRegistry(_FakeSession)
    assert registry.color_of("no-such-game", "alice") is None


# --- game_of (Step 12: Play returns a held seat instead of matchmaking) -----

def test_game_of_returns_the_game_a_seated_username_is_in():
    registry = GameRegistry(_FakeSession)
    game_id = registry.create()
    registry.join(game_id, "alice")
    assert registry.game_of("alice") == game_id


def test_game_of_returns_none_for_a_username_with_no_seat_anywhere():
    registry = GameRegistry(_FakeSession)
    registry.create()
    assert registry.game_of("alice") is None


def test_game_of_still_finds_the_game_after_alice_disconnects():
    # The seat is kept on leave() (Step 5/9), so this must keep finding
    # the game even though alice is no longer connected -- that gap is
    # exactly what a disconnect countdown counts down inside.
    registry = GameRegistry(_FakeSession)
    game_id = registry.create()
    registry.join(game_id, "alice")
    registry.leave(game_id, "alice")
    assert registry.game_of("alice") == game_id


def test_game_of_returns_none_once_the_game_has_ended():
    registry = GameRegistry(_capturing_session)
    game_id = registry.create()
    registry.join(game_id, "alice")  # w
    registry.join(game_id, "bob")    # b
    session = registry.session(game_id)
    session.submit(protocol.move((0, 1), (0, 2)))
    registry.advance(wait_for(1))  # captures, ends the game
    assert registry.game_of("alice") is None


def test_game_of_finds_a_viewer_seat_too():
    registry = GameRegistry(_FakeSession)
    game_id = registry.create()
    registry.join(game_id, "alice")
    registry.join(game_id, "bob")
    registry.join(game_id, "carol")  # viewer
    assert registry.game_of("carol") == game_id


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


# --- disconnect countdown / auto-resign (Step 9, slide 5.2) ----------------

def test_leave_by_a_seated_player_starts_a_countdown_reported_by_countdown_ms():
    registry = GameRegistry(_FakeSession)
    game_id = registry.create()
    registry.join(game_id, "alice")
    registry.leave(game_id, "alice")
    assert registry.countdown_ms(game_id) == {"alice": DISCONNECT_GRACE_MS}


def test_leave_by_a_viewer_starts_no_countdown():
    registry = GameRegistry(_FakeSession)
    game_id = registry.create()
    registry.join(game_id, "alice")  # w
    registry.join(game_id, "bob")    # b
    registry.join(game_id, "carol")  # viewer
    registry.leave(game_id, "carol")
    assert registry.countdown_ms(game_id) == {}


def test_advance_reduces_the_remaining_time():
    registry = GameRegistry(_FakeSession)
    game_id = registry.create()
    registry.join(game_id, "alice")
    registry.leave(game_id, "alice")
    registry.advance(1000)
    assert registry.countdown_ms(game_id) == {"alice": DISCONNECT_GRACE_MS - 1000}


def test_rejoining_before_the_grace_period_clears_the_countdown_entirely():
    registry = GameRegistry(_FakeSession)
    game_id = registry.create()
    registry.join(game_id, "alice")
    registry.leave(game_id, "alice")
    registry.advance(5000)
    registry.join(game_id, "alice")
    assert registry.countdown_ms(game_id) == {}
    # Confirms the entry was actually removed, not merely reset to 0 and
    # still ticking -- either would satisfy the check above on its own.
    registry.advance(1000)
    assert registry.countdown_ms(game_id) == {}


def test_reaching_the_grace_period_publishes_game_end_with_the_opponent_as_winner():
    bus = Bus()
    published = []
    bus.subscribe(topics.GAME_END, published.append)
    registry = GameRegistry(_FakeSession, bus=bus)
    game_id = registry.create()
    registry.join(game_id, "alice")  # w
    registry.join(game_id, "bob")    # b
    registry.leave(game_id, "alice")
    registry.advance(DISCONNECT_GRACE_MS)
    assert len(published) == 1
    payload = published[0]
    assert payload["game_id"] == game_id
    assert payload["winner"] == "b"
    assert payload["seats"] == {"alice": "w", "bob": "b"}


def test_both_players_away_past_the_grace_period_gives_winner_none():
    bus = Bus()
    published = []
    bus.subscribe(topics.GAME_END, published.append)
    registry = GameRegistry(_FakeSession, bus=bus)
    game_id = registry.create()
    registry.join(game_id, "alice")  # w
    registry.join(game_id, "bob")    # b
    registry.leave(game_id, "alice")
    registry.leave(game_id, "bob")
    registry.advance(DISCONNECT_GRACE_MS)
    assert len(published) == 1
    assert published[0]["winner"] is None


def test_a_game_already_ended_by_king_capture_does_not_also_auto_resign():
    bus = Bus()
    published = []
    bus.subscribe(topics.GAME_END, published.append)
    registry = GameRegistry(_capturing_session, bus=bus)
    game_id = registry.create()
    registry.join(game_id, "alice")  # w
    registry.join(game_id, "bob")    # b

    session = registry.session(game_id)
    session.submit(protocol.move((0, 1), (0, 2)))  # captures black's king
    registry.advance(wait_for(1))  # ends the game by king capture

    registry.leave(game_id, "alice")  # starts a countdown, harmlessly
    registry.advance(DISCONNECT_GRACE_MS)  # must not also auto-resign

    assert len(published) == 1
    assert published[0]["winner"] == "w"  # from the king capture, not a resign


def test_game_end_is_published_exactly_once_when_a_countdown_expires():
    bus = Bus()
    published = []
    bus.subscribe(topics.GAME_END, published.append)
    registry = GameRegistry(_FakeSession, bus=bus)
    game_id = registry.create()
    registry.join(game_id, "alice")
    registry.join(game_id, "bob")
    registry.leave(game_id, "alice")
    registry.advance(DISCONNECT_GRACE_MS)
    registry.advance(1000)
    registry.advance(1000)
    assert len(published) == 1


def test_game_is_removed_once_the_linger_period_elapses_after_auto_resign():
    registry = GameRegistry(_FakeSession)
    game_id = registry.create()
    registry.join(game_id, "alice")
    registry.join(game_id, "bob")
    registry.leave(game_id, "alice")
    registry.advance(DISCONNECT_GRACE_MS - 100)  # not yet expired
    # The call that crosses the threshold counts its own ms toward the
    # linger period too (documented on advance() and already exercised by
    # test_a_finished_game_is_still_present_before_the_linger_period_
    # elapses above), so it is kept small here on purpose -- a single
    # advance(DISCONNECT_GRACE_MS) would also already satisfy the much
    # shorter GAME_END_LINGER_MS and delete the game in the same call.
    registry.advance(100)
    assert registry.session(game_id) is not None

    registry.advance(GAME_END_LINGER_MS - 100)
    assert registry.session(game_id) is None
    assert game_id not in registry.game_ids()


def test_countdown_ms_on_an_unknown_game_returns_an_empty_mapping():
    registry = GameRegistry(_FakeSession)
    assert registry.countdown_ms("no-such-game") == {}


def test_a_lone_player_whose_countdown_expires_with_no_opponent_ever_seated_gets_no_winner():
    # A game where only one player ever joined (the other seat was never
    # taken -- the ordinary "waiting for an opponent" state) must not
    # declare the empty seat the winner once the lone player's countdown
    # expires: nobody was ever present on that side either, so this ends
    # the same way "both away" does -- winner=None -- rather than crediting
    # a color nobody ever played.
    bus = Bus()
    published = []
    bus.subscribe(topics.GAME_END, published.append)
    registry = GameRegistry(_FakeSession, bus=bus)
    game_id = registry.create()
    registry.join(game_id, "alice")  # w; "b" is never taken
    registry.leave(game_id, "alice")
    registry.advance(DISCONNECT_GRACE_MS)
    assert len(published) == 1
    assert published[0]["winner"] is None


# --- has_connected_players (Step 9 bug fix) ---------------------------------

def test_has_connected_players_is_true_right_after_joining():
    registry = GameRegistry(_FakeSession)
    game_id = registry.create()
    registry.join(game_id, "alice")
    assert registry.has_connected_players(game_id) is True


def test_has_connected_players_is_false_once_everyone_has_left():
    registry = GameRegistry(_FakeSession)
    game_id = registry.create()
    registry.join(game_id, "alice")
    registry.leave(game_id, "alice")
    assert registry.has_connected_players(game_id) is False


def test_has_connected_players_is_false_for_an_unknown_game():
    registry = GameRegistry(_FakeSession)
    assert registry.has_connected_players("no-such-game") is False
