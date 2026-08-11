"""OpenCV client for Kung-Fu Chess, driven by a remote server instead of a
local engine.

app.py's frame loop is clock.tick() -> engine.snapshot() -> renderer.render().
This package keeps only renderer.render(): there is no local engine and no
clock to tick, because the server owns both. Controller is wired to a
common.net.ClientProxy instead of a real GameEngine, so a click still calls
request_move/request_jump exactly as it does in app.py -- the only difference
is that the proxy serialises the call with `protocol` and sends it to the
server instead of touching a board. That is the whole point of the seam:
app.py's own Controller and BoardMapper needed zero changes to swap sides of
the wire.

A background thread (client.link._ServerLink) owns an asyncio event loop
that talks to the server: it receives `state` messages, decodes them, and
stores the latest GameSnapshot for the draw loop to read. Keeping that
thread separate from the OpenCV loop means a slow or stalled network never
freezes the window -- the draw loop simply keeps redrawing whatever
snapshot it last saw. Sending is bridged the other way with
asyncio.run_coroutine_threadsafe, so a click on the OpenCV thread can hand
its message to the network thread's loop without blocking.

Split by subject: board.py (the read-only snapshot-backed board Controller
selects against), link.py (the network connection), login.py (terminal
login and the waits around it), draw.py (small per-frame drawing helpers),
play.py (the mouse callback and the per-game frame loop), composition.py
(build_client and run() -- the composition root and main loop). This file
is the package's `python -m client` entry point and nothing else; see
composition.py's own module docstring for the client's actual structure.

Run with:  python -m client
"""
import logging

from client.composition import run
# Re-exported for tests/unit/test_main_on_mouse.py, which imports it from
# here -- see client.play's own module docstring for where it now lives.
from client.play import _make_on_mouse  # pylint: disable=unused-import

if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    # Console (above) is for watching a session live; per-client file
    # logging (below) is for looking at one afterward -- slide 6 wants
    # both, and this is what makes there be a file to look at. Configured
    # by client.login._login() itself, once a login actually succeeds --
    # see its own docstring for why not here: the username a file is
    # named after is not known, or even final, until then.
    run()
