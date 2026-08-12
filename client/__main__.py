"""OpenCV client for Kung-Fu Chess, driven by a remote server instead of a
local engine.

Controller and BoardMapper are unchanged from the local version; only the
engine they drive differs -- a ClientProxy that serialises each click as a
`protocol` message instead of touching a board directly. A background
thread (client.link._ServerLink) owns the network connection so a slow or
stalled server never freezes the window: the draw loop just keeps
redrawing whatever snapshot it last received.

Run with:  python -m client
"""
import logging

from client.composition import run
# Re-exported for tests/unit/test_main_on_mouse.py, which imports it from
# here.
from client.play import _make_on_mouse  # pylint: disable=unused-import

if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    # Console logging (above) is for watching a session live; per-client
    # file logging is added later, by client.login._login(), once login
    # succeeds -- the username a log file is named after isn't known
    # until then.
    run()
