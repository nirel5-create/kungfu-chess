from common import net, protocol
from engine.game import GameEngine
from model.board import Board
from tests.helpers import CFG, render, wait_for


def _one_rook_session():
    board = Board([["wR", ".", "."]], CFG)
    engine = GameEngine(board, CFG)
    return net.GameSession(engine), board


def test_a_submitted_move_message_moves_the_piece_after_advancing_past_its_travel_time():
    session, board = _one_rook_session()
    session.submit(protocol.move((0, 0), (0, 1)))
    session.advance(wait_for(1))
    assert render(board) == ". wR ."


def test_a_submitted_move_message_does_not_move_the_piece_before_advancing():
    session, board = _one_rook_session()
    session.submit(protocol.move((0, 0), (0, 1)))
    assert render(board) == "wR . ."


def test_a_submitted_jump_message_reaches_the_engine_as_an_airborne_state():
    session, _board = _one_rook_session()
    session.submit(protocol.jump((0, 0)))
    piece = next(p for p in session.snapshot().pieces if p.kind == "R")
    assert piece.state == "jumping"


def test_an_unknown_message_type_is_ignored_and_the_snapshot_is_unchanged():
    session, board = _one_rook_session()
    before = session.snapshot()
    session.submit({"type": "not_a_real_type"})
    assert session.snapshot() == before
    assert render(board) == "wR . ."


def test_game_over_reflects_the_engine_after_a_king_capture():
    board = Board([["wR", "bK"]], CFG)
    engine = GameEngine(board, CFG)
    session = net.GameSession(engine)
    session.submit(protocol.move((0, 0), (0, 1)))
    session.advance(wait_for(1))
    assert session.game_over is True


# --- ownership (Step 4) -------------------------------------------------

def _two_rook_session():
    """A white rook and a black rook, with an empty cell between them, so a
    move can be tried against a piece that does not belong to the acting
    color, or against the empty cell itself."""
    board = Board([["wR", ".", "bR"]], CFG)
    engine = GameEngine(board, CFG)
    return net.GameSession(engine), board


def test_with_color_w_a_move_of_a_white_piece_is_applied():
    session, board = _two_rook_session()
    session.submit(protocol.move((0, 0), (0, 1)), color="w")
    session.advance(wait_for(1))
    assert render(board) == ". wR bR"


def test_with_color_w_a_move_of_a_black_piece_is_ignored():
    session, board = _two_rook_session()
    before = session.snapshot()
    session.submit(protocol.move((0, 2), (0, 1)), color="w")
    assert session.snapshot() == before
    assert render(board) == "wR . bR"


def test_with_color_b_a_move_of_a_black_piece_is_applied():
    session, board = _two_rook_session()
    session.submit(protocol.move((0, 2), (0, 1)), color="b")
    session.advance(wait_for(1))
    assert render(board) == "wR bR ."


def test_with_color_b_a_move_of_a_white_piece_is_ignored():
    session, board = _two_rook_session()
    before = session.snapshot()
    session.submit(protocol.move((0, 0), (0, 1)), color="b")
    assert session.snapshot() == before
    assert render(board) == "wR . bR"


def test_with_color_viewer_a_move_of_either_color_is_ignored():
    session, board = _two_rook_session()
    before = session.snapshot()
    session.submit(protocol.move((0, 0), (0, 1)), color="viewer")
    session.submit(protocol.move((0, 2), (0, 1)), color="viewer")
    assert session.snapshot() == before
    assert render(board) == "wR . bR"


def test_with_any_color_both_white_and_black_pieces_can_be_moved():
    white_session, white_board = _two_rook_session()
    white_session.submit(protocol.move((0, 0), (0, 1)), color=net.ANY_COLOR)
    white_session.advance(wait_for(1))
    assert render(white_board) == ". wR bR"

    black_session, black_board = _two_rook_session()
    black_session.submit(protocol.move((0, 2), (0, 1)), color=net.ANY_COLOR)
    black_session.advance(wait_for(1))
    assert render(black_board) == "wR bR ."


def test_submit_with_no_color_argument_behaves_as_any_color():
    session, board = _two_rook_session()
    session.submit(protocol.move((0, 0), (0, 1)))
    session.advance(wait_for(1))
    assert render(board) == ". wR bR"


def test_a_jump_is_subject_to_the_same_ownership_check_as_a_move():
    session, _board = _two_rook_session()

    session.submit(protocol.jump((0, 2)), color="w")  # wrong color
    black_piece = next(p for p in session.snapshot().pieces if p.color == "b")
    assert black_piece.state != "jumping"

    session.submit(protocol.jump((0, 2)), color="b")  # correct color
    black_piece = next(p for p in session.snapshot().pieces if p.color == "b")
    assert black_piece.state == "jumping"


def test_a_move_whose_src_names_an_empty_cell_is_ignored_with_no_raise():
    session, board = _two_rook_session()
    before = session.snapshot()
    session.submit(protocol.move((0, 1), (0, 0)), color="w")  # (0, 1) is empty
    assert session.snapshot() == before
    assert render(board) == "wR . bR"
