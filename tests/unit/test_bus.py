from common.bus import Bus


def test_publish_with_no_subscribers_returns_zero_and_does_not_raise():
    bus = Bus()
    assert bus.publish("no.such.topic", "payload") == 0


def test_a_subscribed_handler_receives_the_exact_payload_object():
    bus = Bus()
    received = []
    bus.subscribe("topic", received.append)
    payload = {"marker": object()}
    bus.publish("topic", payload)
    assert received == [payload]
    assert received[0] is payload


def test_two_handlers_on_one_topic_are_both_called_in_subscription_order():
    bus = Bus()
    order = []
    bus.subscribe("topic", lambda payload: order.append("first"))
    bus.subscribe("topic", lambda payload: order.append("second"))
    bus.publish("topic")
    assert order == ["first", "second"]


def test_a_handler_subscribed_to_another_topic_is_not_called():
    bus = Bus()
    calls = []
    bus.subscribe("topic_a", lambda payload: calls.append("a"))
    bus.subscribe("topic_b", lambda payload: calls.append("b"))
    bus.publish("topic_a")
    assert calls == ["a"]


def test_publish_returns_the_number_of_handlers_called():
    bus = Bus()
    bus.subscribe("topic", lambda payload: None)
    bus.subscribe("topic", lambda payload: None)
    bus.subscribe("topic", lambda payload: None)
    assert bus.publish("topic") == 3


def test_unsubscribe_stops_further_delivery_to_that_handler_only():
    bus = Bus()
    calls = []
    unsubscribe = bus.subscribe("topic", lambda payload: calls.append("removed"))
    bus.subscribe("topic", lambda payload: calls.append("kept"))
    unsubscribe()
    bus.publish("topic")
    assert calls == ["kept"]


def test_calling_unsubscribe_twice_is_safe():
    bus = Bus()
    unsubscribe = bus.subscribe("topic", lambda payload: None)
    unsubscribe()
    unsubscribe()
    assert bus.subscriber_count("topic") == 0


def test_the_same_handler_subscribed_twice_is_called_twice():
    bus = Bus()
    calls = []

    def handler(payload):
        calls.append(payload)

    bus.subscribe("topic", handler)
    bus.subscribe("topic", handler)
    bus.publish("topic", "payload")
    assert calls == ["payload", "payload"]


def test_a_raising_handler_does_not_prevent_later_handlers_from_being_called():
    bus = Bus()
    calls = []

    def raising_handler(payload):
        raise ValueError("boom")

    bus.subscribe("topic", raising_handler)
    bus.subscribe("topic", lambda payload: calls.append("later"))
    count = bus.publish("topic")
    assert calls == ["later"]
    assert count == 2


def test_subscriber_count_reflects_subscribes_and_unsubscribes():
    bus = Bus()
    assert bus.subscriber_count("topic") == 0
    unsubscribe_first = bus.subscribe("topic", lambda payload: None)
    assert bus.subscriber_count("topic") == 1
    bus.subscribe("topic", lambda payload: None)
    assert bus.subscriber_count("topic") == 2
    unsubscribe_first()
    assert bus.subscriber_count("topic") == 1


def test_subscribing_from_inside_a_handler_does_not_affect_the_publish_in_progress():
    bus = Bus()
    calls = []

    def subscribes_a_new_handler(payload):
        calls.append("original")
        bus.subscribe("topic", lambda payload: calls.append("late joiner"))

    bus.subscribe("topic", subscribes_a_new_handler)
    count = bus.publish("topic")
    assert calls == ["original"]
    assert count == 1
    assert bus.subscriber_count("topic") == 2


def test_unsubscribing_from_inside_a_handler_does_not_affect_the_publish_in_progress():
    bus = Bus()
    calls = []
    unsubscribe_second = None

    def unsubscribes_the_other_handler(payload):
        calls.append("first")
        unsubscribe_second()

    def second_handler(payload):
        calls.append("second")

    bus.subscribe("topic", unsubscribes_the_other_handler)
    unsubscribe_second = bus.subscribe("topic", second_handler)
    count = bus.publish("topic")
    assert calls == ["first", "second"]
    assert count == 2
    assert bus.subscriber_count("topic") == 1


def test_publish_with_no_payload_argument_delivers_none():
    bus = Bus()
    received = []
    bus.subscribe("topic", received.append)
    bus.publish("topic")
    assert received == [None]
