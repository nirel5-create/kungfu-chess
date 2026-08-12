"""Synchronous, in-process publish/subscribe bus shared by client and server."""

import logging


class Bus:
    """A synchronous, in-process publish/subscribe bus, decoupling a
    producer from its consumers by topic name: the producer does not know
    who listens, and a listener does not know who published. No wildcard
    topics, priorities, async delivery, or replay -- callers needing those
    are a new class, not a flag on this one."""

    def __init__(self):
        self._subscribers = {}  # topic -> list of (token, handler)

    def subscribe(self, topic, handler):
        """Register `handler` for `topic`. -> a zero-argument callable that
        removes this one subscription (idempotent). The same handler may
        subscribe to the same topic more than once; each registration is
        independent, tracked by its own token."""
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
        """Call every handler subscribed to `topic`, passing `payload`, over
        a snapshot of the handler list (safe if a handler subscribes or
        unsubscribes from inside itself). An unsubscribed topic is a silent
        no-op. A handler that raises is caught and logged, not allowed to
        stop the rest. -> how many handlers were called."""
        handlers = [handler for _, handler in self._subscribers.get(topic, [])]
        for handler in handlers:
            try:
                handler(payload)
            except Exception:  # pylint: disable=W0718
                # Deliberate: one bad handler must never stop the others.
                logging.getLogger(__name__).exception(
                    "Bus handler for topic %r raised", topic)
        return len(handlers)

    def subscriber_count(self, topic):
        """-> int. How many handlers are currently subscribed to `topic`."""
        return len(self._subscribers.get(topic, []))
