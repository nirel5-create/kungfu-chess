from common.registry import GameRegistry
from server import _create_room, _find_or_create_game, _join_room


class _FakeSession:
    """A minimal stand-in for GameSession -- these tests are about which
    game_id gets chosen, not about game state, so nothing here needs a
    real board (same reasoning as tests/unit/test_registry.py's own
    _FakeSession)."""

    def __init__(self):
        self.game_over = False

    def advance(self, ms):  # pylint: disable=unused-argument
        pass


def _registry():
    return GameRegistry(_FakeSession)


# --- _create_room -----------------------------------------------------------

def test_create_room_makes_a_game_named_after_the_room():
    registry = _registry()
    game_id = _create_room(registry, "cocorico")
    assert game_id == "cocorico"
    assert "cocorico" in registry.game_ids()


def test_create_room_refuses_a_name_already_in_use():
    registry = _registry()
    _create_room(registry, "cocorico")
    assert _create_room(registry, "cocorico") is None


# --- _join_room ---------------------------------------------------------------

def test_join_room_returns_the_id_of_an_existing_room():
    registry = _registry()
    _create_room(registry, "cocorico")
    assert _join_room(registry, "cocorico") == "cocorico"


def test_join_room_refuses_and_does_not_create_a_nonexistent_room():
    # The bug this guards against: room_join must never silently create
    # the room it was asked to join. Checked both ways -- the refusal
    # itself, and that nothing was created as a side effect of trying.
    registry = _registry()
    assert _join_room(registry, "nosuchroom") is None
    assert "nosuchroom" not in registry.game_ids()


# --- _find_or_create_game -----------------------------------------------------

def test_find_or_create_game_creates_one_on_first_call():
    registry = _registry()
    default_game = {"id": None}
    game_id = _find_or_create_game(registry, default_game, "alice")
    assert game_id in registry.game_ids()
    assert default_game["id"] == game_id


def test_find_or_create_game_reuses_the_same_game_across_calls():
    registry = _registry()
    default_game = {"id": None}
    first = _find_or_create_game(registry, default_game, "alice")
    # Real usage always joins right after -- see server.py's
    # _handle_client -- which is what makes the game "have a connected
    # player" for the next call to find.
    registry.join(first, "alice")
    second = _find_or_create_game(registry, default_game, "bob")
    assert first == second


def test_find_or_create_game_never_returns_a_room():
    # The bug this guards against, found by testing Step 7 live: scanning
    # the registry for "any open game" used to pick up a room created via
    # _create_room, silently placing a Play/Cancel client into someone
    # else's still-open room instead of the ordinary shared game.
    registry = _registry()
    room_id = _create_room(registry, "cocorico")
    default_game = {"id": None}
    game_id = _find_or_create_game(registry, default_game, "alice")
    assert game_id != room_id


def test_find_or_create_game_creates_a_fresh_one_once_the_remembered_game_ends():
    registry = _registry()
    default_game = {"id": None}
    first = _find_or_create_game(registry, default_game, "alice")
    registry.session(first).game_over = True
    second = _find_or_create_game(registry, default_game, "alice")
    assert second != first
    assert default_game["id"] == second


def test_find_or_create_game_skips_a_default_game_with_no_connected_players():
    # The bug this guards against, found by manual testing: a player
    # joined the default game as white, closed the window (the seat is
    # kept, not freed -- see GameRegistry.join/leave), and a stranger who
    # arrived afterward used to be handed that same abandoned game,
    # waiting for an opponent who had already left.
    registry = _registry()
    default_game = {"id": None}
    first = _find_or_create_game(registry, default_game, "alice")
    registry.join(first, "alice")
    registry.leave(first, "alice")  # alice disconnects; her seat stays

    second = _find_or_create_game(registry, default_game, "bob")  # a stranger

    assert second != first
    assert default_game["id"] == second


def test_find_or_create_game_still_returns_the_original_player_to_their_seat():
    # The exception that preserves reconnecting: the same abandoned game
    # as above, but this time it is alice herself coming back, not a
    # stranger -- she must land back in the game she left, not a new one.
    registry = _registry()
    default_game = {"id": None}
    first = _find_or_create_game(registry, default_game, "alice")
    registry.join(first, "alice")
    registry.leave(first, "alice")

    second = _find_or_create_game(registry, default_game, "alice")

    assert second == first
