import json

import pytest

from common import protocol
from common.protocol import CaptureEntry, ProtocolError
from model.board import Board
from model.config import Config
from model.position import Position
from model.snapshot import GameSnapshot, PieceView
from tests.helpers import CFG, make_game


def _small_snapshot(selected_cell=None):
    board = Board([["wR", "."], [".", "bK"]], CFG)
    engine, _ = make_game(board, CFG)
    return engine.snapshot(selected_cell=selected_cell)


# --- 1. builders ------------------------------------------------------------

def test_every_builder_produces_a_dict_whose_type_matches_its_constant():
    assert protocol.move((0, 0), (0, 1))["type"] == protocol.MOVE
    assert protocol.jump((1, 1))["type"] == protocol.JUMP
    assert protocol.play()["type"] == protocol.PLAY
    assert protocol.room_create("my room")["type"] == protocol.ROOM_CREATE
    assert protocol.room_join("room-id")["type"] == protocol.ROOM_JOIN
    assert protocol.state(_small_snapshot())["type"] == protocol.STATE
    assert protocol.assigned("w")["type"] == protocol.ASSIGNED
    assert protocol.countdown(5)["type"] == protocol.COUNTDOWN
    assert protocol.game_over("w")["type"] == protocol.GAME_OVER
    assert protocol.matchmaking("searching")["type"] == protocol.MATCHMAKING
    assert protocol.room("room-id")["type"] == protocol.ROOM
    assert protocol.error("bad move")["type"] == protocol.ERROR


# --- 2. round trip, one message of each type --------------------------------

def test_loads_of_dumps_round_trips_for_one_message_of_each_type():
    messages = [
        protocol.move((0, 0), (1, 1)),
        protocol.jump((2, 2)),
        protocol.play(),
        protocol.room_create("my room"),
        protocol.room_join("room-id"),
        protocol.state(_small_snapshot()),
        protocol.assigned("w"),
        protocol.countdown(5),
        protocol.game_over("b", rating={"you": 1180, "delta": -20}),
        protocol.matchmaking("searching"),
        protocol.room("room-id"),
        protocol.error("bad move"),
    ]
    for message in messages:
        assert protocol.loads(protocol.dumps(message)) == message


# --- 3-8. loads validation ---------------------------------------------------

def test_malformed_json_raises_protocol_error_malformed_json():
    with pytest.raises(ProtocolError) as excinfo:
        protocol.loads("{not valid json")
    assert excinfo.value.code == ProtocolError.MALFORMED_JSON


def test_a_json_list_raises_not_an_object():
    with pytest.raises(ProtocolError) as excinfo:
        protocol.loads("[1, 2, 3]")
    assert excinfo.value.code == ProtocolError.NOT_AN_OBJECT


def test_a_dict_without_type_raises_missing_type():
    with pytest.raises(ProtocolError) as excinfo:
        protocol.loads(json.dumps({"src": [0, 0]}))
    assert excinfo.value.code == ProtocolError.MISSING_TYPE


def test_an_unknown_type_raises_unknown_type():
    with pytest.raises(ProtocolError) as excinfo:
        protocol.loads(json.dumps({"type": "not_a_real_type"}))
    assert excinfo.value.code == ProtocolError.UNKNOWN_TYPE


def test_a_move_missing_dst_raises_bad_payload():
    with pytest.raises(ProtocolError) as excinfo:
        protocol.loads(json.dumps({"type": protocol.MOVE, "src": [0, 0]}))
    assert excinfo.value.code == ProtocolError.BAD_PAYLOAD


def test_a_game_over_missing_winner_username_raises_bad_payload():
    with pytest.raises(ProtocolError) as excinfo:
        protocol.loads(json.dumps({"type": protocol.GAME_OVER, "winner": "w"}))
    assert excinfo.value.code == ProtocolError.BAD_PAYLOAD


# --- game_over's winner_username (winner-by-username, not by color) --------

def test_game_over_defaults_winner_username_to_none():
    assert protocol.game_over("w")["winner_username"] is None


def test_game_over_carries_the_winner_username_through_a_round_trip():
    message = protocol.game_over("w", winner_username="alice")
    round_tripped = protocol.loads(protocol.dumps(message))
    assert round_tripped["winner_username"] == "alice"


def test_game_over_with_no_winner_has_no_winner_username_either():
    message = protocol.game_over(None)
    assert message["winner"] is None
    assert message["winner_username"] is None


# --- history (Step 11: move log, scores, real names) ------------------------

def test_history_message_type_matches_its_constant():
    message = protocol.history("alice", "bob", 3, 5, ())
    assert message["type"] == protocol.HISTORY


def test_history_round_trips_with_names_scores_and_an_empty_log():
    message = protocol.history("alice", "bob", 3, 5, ())
    round_tripped = protocol.loads(protocol.dumps(message))
    assert round_tripped["white_name"] == "alice"
    assert round_tripped["black_name"] == "bob"
    assert round_tripped["white_score"] == 3
    assert round_tripped["black_score"] == 5
    assert round_tripped["log"] == []


def test_a_history_missing_a_required_field_raises_bad_payload():
    with pytest.raises(ProtocolError) as excinfo:
        protocol.loads(json.dumps({
            "type": protocol.HISTORY, "white_name": "alice", "black_name": "bob",
            "white_score": 0, "black_score": 0,
        }))  # "log" missing
    assert excinfo.value.code == ProtocolError.BAD_PAYLOAD


def test_decode_capture_log_round_trips_capture_entries_in_order():
    log = (
        CaptureEntry(capturer_color="w", victim_token="bP", cost=1, clock_ms=500),
        CaptureEntry(capturer_color="b", victim_token="wN", cost=3, clock_ms=1500),
    )
    message = protocol.history("alice", "bob", 1, 3, log)
    round_tripped = protocol.loads(protocol.dumps(message))
    decoded = protocol.decode_capture_log(round_tripped["log"])
    assert decoded == log


def test_decode_capture_log_of_an_empty_list_is_an_empty_tuple():
    assert protocol.decode_capture_log([]) == ()


def test_decode_capture_log_raises_bad_payload_on_a_malformed_entry():
    with pytest.raises(ProtocolError) as excinfo:
        protocol.decode_capture_log([{"capturer_color": "w"}])  # missing fields
    assert excinfo.value.code == ProtocolError.BAD_PAYLOAD


# --- rating (Step 12: shown in the home dialog) ------------------------------

def test_rating_message_type_matches_its_constant():
    assert protocol.rating(1200)["type"] == protocol.RATING


def test_rating_round_trips():
    message = protocol.rating(1187)
    round_tripped = protocol.loads(protocol.dumps(message))
    assert round_tripped["rating"] == 1187


def test_a_rating_missing_its_field_raises_bad_payload():
    with pytest.raises(ProtocolError) as excinfo:
        protocol.loads(json.dumps({"type": protocol.RATING}))
    assert excinfo.value.code == ProtocolError.BAD_PAYLOAD


# --- waiting (live-testing fix: no game runs with only one player) ----------

def test_waiting_message_type_matches_its_constant():
    assert protocol.waiting(True)["type"] == protocol.WAITING


def test_waiting_round_trips():
    message = protocol.waiting(True)
    round_tripped = protocol.loads(protocol.dumps(message))
    assert round_tripped["waiting"] is True


def test_a_waiting_missing_its_field_raises_bad_payload():
    with pytest.raises(ProtocolError) as excinfo:
        protocol.loads(json.dumps({"type": protocol.WAITING}))
    assert excinfo.value.code == ProtocolError.BAD_PAYLOAD


def test_a_move_whose_src_is_not_a_two_element_int_list_raises_bad_payload():
    with pytest.raises(ProtocolError) as excinfo:
        protocol.loads(json.dumps({"type": protocol.MOVE, "src": [0], "dst": [1, 1]}))
    assert excinfo.value.code == ProtocolError.BAD_PAYLOAD


# --- 9-12. snapshot round trip ----------------------------------------------

def test_snapshot_round_trip_from_a_real_engine_matches_field_for_field():
    snapshot = _small_snapshot()
    decoded = protocol.decode_snapshot(protocol.encode_snapshot(snapshot))
    assert decoded == snapshot
    assert isinstance(decoded.pieces, tuple)
    assert all(isinstance(piece, PieceView) for piece in decoded.pieces)


def test_snapshot_round_trip_with_selected_cell_none():
    snapshot = _small_snapshot(selected_cell=None)
    decoded = protocol.decode_snapshot(protocol.encode_snapshot(snapshot))
    assert decoded.selected_cell is None


def test_snapshot_round_trip_with_selected_cell_set_decodes_to_position():
    snapshot = _small_snapshot(selected_cell=Position(0, 0))
    decoded = protocol.decode_snapshot(protocol.encode_snapshot(snapshot))
    assert decoded.selected_cell == Position(0, 0)
    assert isinstance(decoded.selected_cell, Position)


def test_a_snapshot_taken_mid_motion_round_trips_without_losing_precision():
    board = Board([["wR", ".", "."]], CFG)
    engine, _ = make_game(board, CFG)
    engine.request_move((0, 0), (0, 2))
    engine.wait(333)  # partway through the first of two cells
    snapshot = engine.snapshot()
    moving_piece = next(piece for piece in snapshot.pieces if piece.state == "moving")
    assert moving_piece.x != int(moving_piece.x)
    decoded = protocol.decode_snapshot(protocol.encode_snapshot(snapshot))
    assert decoded == snapshot
    assert decoded.pieces[0].x == snapshot.pieces[0].x


def test_state_message_round_trips_and_nested_snapshot_still_decodes():
    snapshot = _small_snapshot(selected_cell=Position(0, 0))
    message = protocol.state(snapshot)
    round_tripped = protocol.loads(protocol.dumps(message))
    assert round_tripped == message
    decoded = protocol.decode_snapshot(round_tripped["snapshot"])
    assert decoded == snapshot


# --- 14-18. corrections and additions ---------------------------------------

def test_decoded_snapshot_board_offset_is_a_tuple_not_a_list():
    snapshot = _small_snapshot()
    decoded = protocol.decode_snapshot(protocol.encode_snapshot(snapshot))
    assert isinstance(decoded.board_offset, tuple)
    assert not isinstance(decoded.board_offset, list)


def test_decoded_snapshot_pieces_is_a_tuple_of_pieceview_instances():
    snapshot = _small_snapshot()
    decoded = protocol.decode_snapshot(protocol.encode_snapshot(snapshot))
    assert isinstance(decoded.pieces, tuple)
    assert all(isinstance(piece, PieceView) for piece in decoded.pieces)


def test_a_decoded_non_none_selected_cell_is_a_position_instance():
    snapshot = _small_snapshot(selected_cell=Position(1, 0))
    decoded = protocol.decode_snapshot(protocol.encode_snapshot(snapshot))
    assert isinstance(decoded.selected_cell, Position)


def test_rest_progress_round_trips_as_a_float_including_a_nonzero_value():
    piece = PieceView(kind="P", color="w", row=0, col=0, x=0.0, y=0.0,
                       state="resting_short", rest_progress=0.42)
    snapshot = GameSnapshot(
        board_width=1, board_height=1, cell_size=100, pieces=(piece,),
        selected_cell=None, game_over=False, board_offset=(0, 0))
    decoded = protocol.decode_snapshot(protocol.encode_snapshot(snapshot))
    assert decoded.pieces[0].rest_progress == 0.42
    assert isinstance(decoded.pieces[0].rest_progress, float)


def test_a_snapshot_with_a_non_default_board_offset_round_trips_exactly():
    config = Config(board_offset=(7, 13))
    board = Board([["wK"]], config)
    engine, _ = make_game(board, config)
    snapshot = engine.snapshot()
    assert snapshot.board_offset == (7, 13)
    decoded = protocol.decode_snapshot(protocol.encode_snapshot(snapshot))
    assert isinstance(decoded.board_offset, tuple)
    assert decoded.board_offset == (7, 13)
    assert decoded == snapshot

# --- decode_snapshot hardening: malformed input raises ProtocolError ---------


def test_decode_snapshot_on_non_dict_raises_bad_payload():
    for bad in (None, [1, 2], "snapshot", 42):
        with pytest.raises(ProtocolError) as excinfo:
            protocol.decode_snapshot(bad)
        assert excinfo.value.code == ProtocolError.BAD_PAYLOAD


def test_decode_snapshot_missing_field_raises_bad_payload():
    with pytest.raises(ProtocolError) as excinfo:
        protocol.decode_snapshot({"board_width": 8, "board_height": 8})
    assert excinfo.value.code == ProtocolError.BAD_PAYLOAD


def test_decode_snapshot_malformed_selected_cell_raises_bad_payload():
    base = protocol.encode_snapshot(_small_snapshot())
    base["selected_cell"] = [1]  # wrong shape: not a 2-element cell
    with pytest.raises(ProtocolError) as excinfo:
        protocol.decode_snapshot(base)
    assert excinfo.value.code == ProtocolError.BAD_PAYLOAD


def test_decode_snapshot_malformed_board_offset_raises_bad_payload():
    base = protocol.encode_snapshot(_small_snapshot())
    base["board_offset"] = [0]  # wrong shape
    with pytest.raises(ProtocolError) as excinfo:
        protocol.decode_snapshot(base)
    assert excinfo.value.code == ProtocolError.BAD_PAYLOAD


def test_decode_snapshot_piece_missing_field_raises_bad_payload():
    base = protocol.encode_snapshot(_small_snapshot())
    base["pieces"] = [{"kind": "R"}]  # a piece dict missing most fields
    with pytest.raises(ProtocolError) as excinfo:
        protocol.decode_snapshot(base)
    assert excinfo.value.code == ProtocolError.BAD_PAYLOAD


def test_state_message_with_garbage_snapshot_is_caught_not_crashed():
    # a structurally valid 'state' envelope whose snapshot is rubbish:
    # loads() passes (the 'snapshot' key exists) but decode must not crash.
    msg = protocol.loads(protocol.dumps({"type": "state", "snapshot": {"board_width": 8}}))
    with pytest.raises(ProtocolError) as excinfo:
        protocol.decode_snapshot(msg["snapshot"])
    assert excinfo.value.code == ProtocolError.BAD_PAYLOAD


# --- login (Step 4) -----------------------------------------------------

def test_login_builder_produces_a_dict_whose_type_matches_its_constant():
    assert protocol.login("nirel")["type"] == protocol.LOGIN


def test_login_round_trips_through_dumps_and_loads():
    message = protocol.login("nirel")
    assert protocol.loads(protocol.dumps(message)) == message


def test_login_missing_username_raises_bad_payload():
    with pytest.raises(ProtocolError) as excinfo:
        protocol.loads(json.dumps({"type": protocol.LOGIN}))
    assert excinfo.value.code == ProtocolError.BAD_PAYLOAD

