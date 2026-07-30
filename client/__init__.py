"""Pure, testable client-side modules that react to the bus (Step 6).

Split out from the root client.py script on purpose: client.py wires sockets
and OpenCV and is untestable by design (see its own module docstring), while
everything in this package is pure -- no sockets, no drawing library calls
except where explicitly noted -- and is exercised by tests/unit/test_events.py,
test_sound.py and test_overlay.py.
"""
