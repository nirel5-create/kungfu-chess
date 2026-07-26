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
