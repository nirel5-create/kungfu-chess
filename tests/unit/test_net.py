from common import net, protocol


def test_client_proxy_request_move_sends_exactly_protocol_move():
    sent = []
    proxy = net.ClientProxy(sent.append)
    proxy.request_move((0, 0), (1, 1))
    assert sent == [protocol.move((0, 0), (1, 1))]


def test_client_proxy_request_jump_sends_exactly_protocol_jump():
    sent = []
    proxy = net.ClientProxy(sent.append)
    proxy.request_jump((2, 2))
    assert sent == [protocol.jump((2, 2))]
