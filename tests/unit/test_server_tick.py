import asyncio

import websockets

from server.tick import _GameBroadcast, _TickState


class _FakeWebSocket:
    def __init__(self, fail=False):
        self.fail = fail
        self.sent = []

    async def send(self, message):
        if self.fail:
            raise websockets.ConnectionClosed(None, None)
        self.sent.append(message)


def test_tick_state_starts_at_zero_with_every_bookkeeping_dict_empty():
    state = _TickState()
    assert state.tick_count == 0
    assert state.ms_since_summary == 0
    assert state.last_countdown_seconds == {}
    assert state.current_countdown_seconds == {}
    assert state.last_history_sent == {}
    assert state.last_waiting_sent == {}


def test_game_broadcast_send_reaches_every_client():
    first, second = _FakeWebSocket(), _FakeWebSocket()
    dead = set()
    broadcast = _GameBroadcast("g1", [first, second], dead)
    asyncio.run(broadcast.send("hello"))
    assert first.sent == ["hello"]
    assert second.sent == ["hello"]
    assert dead == set()


def test_game_broadcast_send_moves_a_failed_client_into_dead():
    ok, failing = _FakeWebSocket(), _FakeWebSocket(fail=True)
    dead = set()
    broadcast = _GameBroadcast("g1", [ok, failing], dead)
    asyncio.run(broadcast.send("hello"))
    assert ok.sent == ["hello"]
    assert dead == {failing}
