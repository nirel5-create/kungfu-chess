"""Synchronous, in-process publish/subscribe bus shared by client and server."""

import logging


class Bus:
    """A synchronous, in-process publish/subscribe bus. It decouples a
    producer from its consumers by topic name: the producer does not know
    who listens, and a listener does not know who published.

    On the client this lets the renderer, the sound player, the move log and
    the start/end animation each react to the same events independently --
    none of them knowing about the socket.

    What Bus owns: a mapping of topic name -> subscribed handlers, and the
    dispatch of a payload to those handlers.
    What Bus does NOT own: threads, queues, ordering across topics, message
    formats, persistence, or any knowledge of what a topic means.

    Non-goals: no wildcard/pattern topics, no priorities, no async delivery,
    no retained/replayed messages. If those are ever needed they are a new
    class, not a flag on this one.
    """

    def __init__(self):
        self._subscribers = {}  # topic -> list of (token, handler)

    def subscribe(self, topic, handler):
        """Register `handler` for `topic`. Returns a zero-argument callable
        that removes this one subscription; calling it twice is safe.

        The same handler may subscribe to the same topic more than once --
        each registration is independent, tracked by its own token, and each
        is called on publish.
        """
        subs = self._subscribers.setdefault(topic, [])
        token = object()
        subs.append((token, handler))

        def unsubscribe():
            for i, (t, _) in enumerate(subs):
                if t is token:
                    del subs[i]
                    return

        return unsubscribe

    def publish(self, topic, payload=None):
        """Call every handler subscribed to `topic`, in subscription order,
        passing `payload`. Returns how many handlers were called.

        A topic with no subscribers is a no-op that returns 0 -- never an
        error; a topic is not "declared" anywhere, it exists when someone
        uses it.

        Handler isolation: if a handler raises, the exception is caught and
        logged, and the remaining handlers still run. One broken subscriber
        must never stop the others -- a crash in the sound player must not
        stop the board from being drawn.

        Iterates over a copy of the handler list, so subscribing or
        unsubscribing from inside a handler does not affect this dispatch.
        """
        handlers = [handler for _, handler in self._subscribers.get(topic, [])]
        for handler in handlers:
            try:
                handler(payload)
            except Exception:  # pylint: disable=W0718
                # Deliberate: one bad handler must never stop the others
                # (see docstring above), so every exception is caught here.
                logging.getLogger(__name__).exception(
                    "Bus handler for topic %r raised", topic)
        return len(handlers)

    def subscriber_count(self, topic):
        """-> int. How many handlers are currently subscribed to `topic`."""
        return len(self._subscribers.get(topic, []))
