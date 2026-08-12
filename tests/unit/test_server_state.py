from server.state import Seat, ServerState


def test_server_state_bundles_the_handed_in_collaborators():
    registry = object()
    db_conn = object()
    matchmaker = object()
    state = ServerState(registry, db_conn, matchmaker)
    assert state.registry is registry
    assert state.db_conn is db_conn
    assert state.play_queue.matchmaker is matchmaker


def test_server_state_starts_every_other_field_empty():
    state = ServerState(registry=object(), db_conn=None, matchmaker=object())
    assert state.clients == {}
    assert state.default_game == {"id": None}
    assert state.play_queue.matchmaking == {}
    assert state.connected_usernames == set()
    assert state.observers == {}


def test_seat_is_game_id_color_username_in_that_order():
    seat = Seat("g1", "w", "alice")
    assert seat.game_id == "g1"
    assert seat.color == "w"
    assert seat.username == "alice"
