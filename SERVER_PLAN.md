# Kung-Fu Chess — Server Phase: Implementation Spec

This file is the contract. Implement exactly what is specified here, one step at a
time. Do not improvise architecture, do not add modules that are not listed, and do
not skip ahead to a later step.

---

## IRON RULES (apply to every step, no exceptions)

1. **Never modify an existing test.** All 292 currently-passing tests must still pass
   after every change. If a change would break a test, the change is wrong — stop and
   report, do not "fix" the test.
2. **Never edit `engine/`, `model/`, `rules/`, `realtime/`, `boardio/`, `texttests/`.**
   These are frozen. The server *imports* them. If you believe an edit is required,
   stop and report instead.
3. **`main.py` stays exactly as it is** — it is the VPL entry point and VPL is graded
   on exact stdout.
4. **Code and comments in English.** Follow the existing house style: a class-level
   docstring saying what the class owns and, explicitly, what it does *not* own.
5. **Every new pure module gets unit tests** in `tests/unit/`. Pure means: no socket,
   no file, no OpenCV, no real clock.
6. **One step per commit.** Run `python -m pytest -q` before every commit and paste
   the summary line.

---

## Package layout introduced by this phase

```
common/          shared by client and server — pure, no I/O
  __init__.py
  bus.py         Bus (pub/sub)
  topics.py      topic name constants
  protocol.py    wire encode/decode
```

Later steps add `server/` and `client/`. Do not create them yet.

---

# STEP 1 — `common/bus.py` + `common/topics.py`

## Purpose

A synchronous, in-process publish/subscribe bus. It decouples a producer from its
consumers by topic name: the producer does not know who listens, and a listener does
not know who published.

This is what Slide 1 asks for. On the client it will let the renderer, the sound
player, the move log and the start/end animation each react to the same events
independently — none of them knowing about the socket.

**What Bus owns:** a mapping of topic name → subscribed handlers, and the dispatch
of a payload to those handlers.
**What Bus does NOT own:** threads, queues, ordering across topics, message
formats, persistence, or any knowledge of what a topic means.

## `common/topics.py`

Topic names live in exactly one place, so a typo is impossible and the full event
vocabulary is readable at a glance. This mirrors how the codebase already keeps
`ERROR_*` strings in one module.

```python
SNAPSHOT     = "snapshot"       # a new GameSnapshot arrived
SCORE_UPDATE = "score_update"   # Slide 1a
MOVE_LOG     = "move_log"       # Slide 1b
SOUND        = "sound"          # Slide 1c
GAME_START   = "game_start"     # Slide 1d
GAME_END     = "game_end"       # Slide 1d
COUNTDOWN    = "countdown"      # disconnect countdown
MATCHMAKING  = "matchmaking"    # Play button status
ROOM         = "room"           # room created / joined
CONNECTION   = "connection"     # connected / disconnected
```

## `common/bus.py` — required API

```python
class Bus:
    def subscribe(self, topic, handler): ...   # -> unsubscribe callable
    def publish(self, topic, payload=None): ...  # -> number of handlers called
    def subscriber_count(self, topic): ...     # -> int
```

### Behaviour, exactly

- `subscribe(topic, handler)` registers `handler` (any callable taking one argument)
  and returns a zero-argument callable that removes that one subscription.
- The same handler may subscribe to the same topic more than once; each registration
  is independent and each is called.
- `publish(topic, payload)` calls every handler subscribed to that topic, **in
  subscription order**, passing `payload`. Returns how many handlers were called.
- Publishing to a topic with no subscribers is a **no-op that returns 0** — never an
  error. A topic is not "declared" anywhere; it exists when someone uses it.
- **Handler isolation:** if a handler raises, catch the exception, log it via
  `logging.getLogger(__name__).exception(...)`, and **continue calling the remaining
  handlers**. One broken subscriber must never stop the others. This is deliberate: a
  crash in the sound player must not stop the board from being drawn.
- Calling the returned unsubscribe callable twice is safe (second call does nothing).
- Subscribing or unsubscribing from *inside* a handler must not corrupt the dispatch
  in progress — iterate over a copy of the handler list in `publish`.

### Non-goals (state these in the docstring)

No wildcard/pattern topics, no priorities, no async delivery, no retained/replayed
messages. If those are ever needed they are a new class, not a flag on this one.

## Tests — `tests/unit/test_bus.py`

Write at least these, one assertion-idea each, with long descriptive names:

1. publish with no subscribers returns 0 and does not raise
2. a subscribed handler receives the exact payload object
3. two handlers on one topic are both called, in subscription order
4. a handler subscribed to another topic is not called
5. publish returns the number of handlers called
6. unsubscribe stops further delivery to that handler only
7. calling unsubscribe twice is safe
8. the same handler subscribed twice is called twice
9. a raising handler does not prevent later handlers from being called
10. `subscriber_count` reflects subscribes and unsubscribes
11. subscribing from inside a handler does not affect the publish in progress
12. `publish` with no payload argument delivers `None`

---

# STEP 2 — `common/protocol.py`

## Purpose

The single source of truth for the wire format, exactly as `boardio` is the single
source of truth for the text format. Nothing else in client or server may build or
parse a message by hand.

**What protocol owns:** message type names, message construction, JSON
encode/decode, and `GameSnapshot` ↔ dict conversion.
**What protocol does NOT own:** sockets, game rules, sessions, or when to send.

## Error type — mirror the existing idiom

Follow `BoardParseError`: a stable, machine-readable code so callers map it to their
own output.

```python
class ProtocolError(Exception):
    MALFORMED_JSON = "MALFORMED_JSON"
    NOT_AN_OBJECT  = "NOT_AN_OBJECT"     # valid JSON but not a dict
    MISSING_TYPE   = "MISSING_TYPE"
    UNKNOWN_TYPE   = "UNKNOWN_TYPE"
    BAD_PAYLOAD    = "BAD_PAYLOAD"       # right type, wrong/missing fields
    def __init__(self, code): ...        # sets self.code
```

## Message types

```python
# client -> server
MOVE        = "move"          {"src": [r,c], "dst": [r,c]}
JUMP        = "jump"          {"cell": [r,c]}
PLAY        = "play"          {}
ROOM_CREATE = "room_create"   {"name": str}
ROOM_JOIN   = "room_join"     {"id": str}

# server -> client
STATE       = "state"         {"snapshot": {...}}
ASSIGNED    = "assigned"      {"color": "w" | "b" | "viewer"}
COUNTDOWN   = "countdown"     {"seconds": int}
GAME_OVER   = "game_over"     {"winner": "w"|"b"|None, "rating": {...}|None}
MATCHMAKING = "matchmaking"   {"status": "searching"|"found"|"timeout"}
ROOM        = "room"          {"id": str}
ERROR       = "error"         {"reason": str}
```

Colors are `"w"` / `"b"` — the same spelling `Config` and `PieceView` already use.
Do not introduce `"white"` / `"black"` anywhere.

Cells are `[row, col]` lists. **Rationale to put in the docstring:** the engine's
command surface (`request_move(src, dst)`) already speaks in cells, so sending cells
means zero translation on either side. The slide's `WQe2e5` is illustrative; if it is
ever wanted on screen, add `format_move_notation()` here and nowhere else.

## Required API

```python
# framing
def dumps(message: dict) -> str
def loads(text: str) -> dict            # validates; raises ProtocolError

# builders (one per message type, each returns a dict)
def move(src, dst) -> dict
def jump(cell) -> dict
def play() -> dict
def room_create(name) -> dict
def room_join(room_id) -> dict
def state(snapshot) -> dict             # takes a GameSnapshot
def assigned(color) -> dict
def countdown(seconds) -> dict
def game_over(winner, rating=None) -> dict
def matchmaking(status) -> dict
def room(room_id) -> dict
def error(reason) -> dict

# snapshot conversion
def encode_snapshot(snapshot) -> dict
def decode_snapshot(data) -> GameSnapshot
```

### `loads` validation, exactly

- not valid JSON → `ProtocolError(MALFORMED_JSON)`
- valid JSON but not a dict (a list, a number, a string) → `NOT_AN_OBJECT`
- dict with no `"type"` key → `MISSING_TYPE`
- `"type"` not in the known set → `UNKNOWN_TYPE`
- known type missing a required field, or a cell that is not a 2-element list of
  ints → `BAD_PAYLOAD`

This matters: the server must never crash because a client sent rubbish. Every
malformed input becomes a `ProtocolError` with a code the caller can turn into an
`error` message.

### `encode_snapshot` / `decode_snapshot`

`GameSnapshot(board_width, board_height, cell_size, pieces, selected_cell, game_over)`
and `PieceView(kind, color, row, col, x, y, state)` are namedtuples of primitives, so
this is a direct walk — no cleverness.

Two details that are easy to get wrong, so handle them explicitly:

- `selected_cell` is a `Position` (a namedtuple) **or `None`**. Encode as `[row, col]`
  or `null`; decode back to `Position(row, col)` or `None`.
- `pieces` must decode back to a **tuple** of `PieceView` (JSON gives a list), because
  the rest of the code treats snapshots as immutable.
- `x` and `y` are floats from interpolation. Keep them as floats; do not round.

## Tests — `tests/unit/test_protocol.py`

1. every builder produces a dict whose `"type"` is the matching constant
2. `loads(dumps(msg)) == msg` for one message of each type
3. malformed JSON raises `ProtocolError` with code `MALFORMED_JSON`
4. a JSON list raises `NOT_AN_OBJECT`
5. a dict without `"type"` raises `MISSING_TYPE`
6. an unknown `"type"` raises `UNKNOWN_TYPE`
7. a `move` missing `"dst"` raises `BAD_PAYLOAD`
8. a `move` whose `"src"` is not a 2-element int list raises `BAD_PAYLOAD`
9. **snapshot round-trip:** build a real engine from a small board, take
   `engine.snapshot()`, then
   `decode_snapshot(encode_snapshot(s)) == s` — field for field, including
   `pieces` being a tuple of `PieceView`
10. snapshot round-trip with `selected_cell=None`
11. snapshot round-trip with a `selected_cell` set, decoding back to a `Position`
12. a snapshot taken mid-motion (non-integer x/y) round-trips without losing precision
13. `state(snapshot)` round-trips through `dumps`/`loads` and the nested snapshot
    still decodes

Use the existing helpers in `tests/helpers.py` for building boards rather than
duplicating setup.
## STEP 2 — CORRECTIONS AND ADDITIONS (authoritative; override anything above)

### Verified namedtuple shapes — use exactly these

    PieceView:    kind color row col x y state rest_progress   (8 fields; rest_progress is a float, default 0.0)
    GameSnapshot: board_width board_height cell_size pieces selected_cell game_over board_offset
                  (7 fields; board_offset is a TUPLE, default (0, 0))

### Full-snapshot decision (state it in the module docstring)

The server sends the COMPLETE board state every tick, never deltas. Every message
is therefore the whole truth, so client and server cannot drift, a reconnecting
client resyncs with no special logic, and a viewer joining mid-game just receives
the current state. Bandwidth is irrelevant for a local two-player server, and
deltas would buy nothing while adding exactly the synchronisation complexity we
are trying to avoid.

### Three round-trip traps — all three are verified real, handle each explicitly

1. `board_offset` is a tuple. JSON turns it into a list, and `(0, 0) != [0, 0]`.
   `decode_snapshot` MUST rebuild it as a tuple.
2. `pieces` is a tuple of PieceView. JSON gives a list. `decode_snapshot` MUST
   rebuild a tuple, and each element MUST be a PieceView, not a list.
3. `Position` subclasses tuple, so `Position(1, 2) == (1, 2)` is True. An equality
   check therefore CANNOT detect that decoding returned a plain tuple instead of a
   Position. Tests MUST assert `isinstance(decoded.selected_cell, Position)`
   in addition to equality. A test that only compares with `==` is green-for-nothing.

### Additional required tests (append to the Step 2 list)

14. a decoded snapshot's `board_offset` is a tuple, not a list
15. a decoded snapshot's `pieces` is a tuple, and each element `isinstance(..., PieceView)`
16. a decoded non-None `selected_cell` satisfies `isinstance(..., Position)`
17. `rest_progress` round-trips as a float, including a non-zero value
18. a snapshot with a non-default `board_offset` (e.g. (7, 13)) round-trips exactly

### Style gate (now enforced)

`python -m pylint common/` must score 10.00/10 before committing. Suppress a
warning only with an explicit code and an inline comment giving the reason, as in
`common/bus.py`.
---
Write-Host "`n[4/4] pylint (must be 10.00/10)" -ForegroundColor Cyan
python -m pylint common model rules realtime engine input boardio view main.py
if ($LASTEXITCODE -ne 0) { Write-Host "PYLINT NOT CLEAN - do not push" -ForegroundColor Red; exit 1 }
## STOP HERE

After Step 2 passes, report back with the test summary. Do **not** start Step 3
(`server/`, `client/`, WebSocket) — that spec comes after these two are reviewed.

# STEP 3 — Minimal server + client over WebSocket

Append this as the Step 3 section of SERVER_PLAN.md. The IRON RULES still apply.
Two additions to them for this step:

- **Line endings:** every new file must be saved with CRLF endings and a final
  newline. (We lost time on mixed LF/CRLF; do not repeat it.)
- **The graphical stack is frozen too:** do not edit `view/`, `input/`, `app.py`,
  or the engine packages. The client *reuses* them. `app.py` stays as the local
  offline front end and keeps working unchanged.
Install the one dependency first: `pip install websockets`.

---

## What this step delivers

Two processes on `localhost`, talking over a real WebSocket:

- **`server.py`** (root) — owns the `GameEngine` + `GameClock`, runs the clock,
  applies commands that arrive from clients, and broadcasts the full snapshot to
  every connected client on every tick.
- **`client.py`** (root) — opens the OpenCV window using the EXISTING graphical
  stack, but instead of driving a local engine it: sends the player's clicks to
  the server as `move`/`jump` messages, and draws whatever snapshot the server
  last sent.
Success looks like: run `python server.py` in one terminal, `python client.py` in
two others; each client window shows the same board; a move clicked in either
window is applied by the server and appears in BOTH windows.

Colour assignment, login, rooms, ELO, disconnect handling are LATER steps. This
step is only: the clock lives on the server, commands go up, snapshots come down,
and the existing renderer draws them.

---

## The key idea (state it in the module docstrings)

`app.py`'s loop is today: `clock.tick()` -> `engine.snapshot()` ->
`renderer.render()`. Step 3 splits that loop across the wire:

- The **server** keeps `clock.tick()` and `engine`, and after each tick sends
  `protocol.state(engine.snapshot())` to all clients.
- The **client** keeps `renderer.render()` and `Controller`, but its "engine" is
  now a thin proxy: `Controller` calls `request_move`/`request_jump` on the proxy,
  and the proxy serialises them with `protocol.move`/`protocol.jump` and sends
  them to the server. The client never runs a real engine and never advances a
  clock; it draws the latest snapshot it received.
`Controller` depends only on the engine's command surface (`request_move`,
`request_jump`), so swapping the real engine for the network proxy needs ZERO
changes to `Controller`, `BoardMapper`, or `view/`. That clean seam is the whole
reason this split is small.

---

## New files

```
server.py            # root: the async WebSocket server + game session
client.py            # root: the OpenCV client that renders server snapshots
common/net.py        # tiny shared helpers for framing over a websocket
tests/unit/test_session.py
tests/unit/test_net.py
```

Do NOT create matchmaking, rooms, accounts, or logging files yet.

---

### `common/net.py` — a testable session, no sockets inside

The sockets live in `server.py`/`client.py`; the *logic* lives here so it can be
unit-tested without a network. Put two pure pieces here:

1. **`GameSession`** — owns one `GameEngine` for a match. No asyncio, no sockets.
   - `__init__(self, engine, clock)` — takes the engine and a clock it can tick.
   - `submit(self, message)` — takes a DECODED command dict (already through
     `protocol.loads`), applies it to the engine: `move` -> `engine.request_move`,
     `jump` -> `engine.request_jump`. Unknown/again-malformed message -> ignored
     (return without raising; the caller already validated via `protocol.loads`,
     this is defence in depth). It does NOT tick the clock.
   - `advance(self, ms)` — tick the clock by `ms` (drives the engine's time).
   - `snapshot(self)` — return `engine.snapshot()`.
   - `game_over` property -> `engine.game_over`.
   Why a class and not loose functions: the server holds exactly one of these per
   game and it is the single place a command is turned into an engine call, so the
   ordering guarantee (commands applied at tick boundaries) has one clear home.
2. **`ClientProxy`** — the fake "engine" the client's `Controller` talks to.
   - `__init__(self, send)` — `send` is a callable taking one already-built
     message dict; the real client passes a function that puts the message on the
     websocket. In tests you pass a list's `.append`.
   - `request_move(self, src, dst)` -> `self._send(protocol.move(src, dst))`
   - `request_jump(self, cell)` -> `self._send(protocol.jump(cell))`
   That is the entire command surface `Controller` uses, so `ClientProxy` is a
   drop-in stand-in for `GameEngine` on the client side.
Both are pure and fully unit-tested. `GameClock` already ticks from a real clock;
`GameSession.advance(ms)` must drive the engine deterministically instead, so in
tests time is explicit. Check GameClock's real API first (`input/game_clock.py`)
and, if it only reads the wall clock, have `GameSession` call `engine.wait(ms)`
directly rather than through the clock — pick whichever keeps time explicit and
test it. Do not invent a clock method that does not exist.

### `tests/unit/test_session.py`

- a `move` message submitted to a session moves the piece after `advance` past its
  travel time (build a tiny board with `tests/helpers`, submit
  `protocol.move(src, dst)` decoded, `advance` enough ms, assert the snapshot)
- a `jump` message reaches the engine (a piece that can jump changes state)
- an unknown message type is ignored, no raise, snapshot unchanged
- `game_over` reflects the engine after a king capture
- `ClientProxy.request_move` sends exactly `protocol.move(src, dst)` to its sink
- `ClientProxy.request_jump` sends exactly `protocol.jump(cell)` to its sink
### `server.py` — asyncio websockets glue (marked `# pragma: no cover`)

Not unit-tested (a live socket, like the OpenCV window). Keep ALL logic in
`GameSession`; this file is only plumbing:

- one module-level `GameSession` for the single game (two-player colour handling
  is the NEXT step; for now every client shares one session and may move any
  piece).
- keep a `set` of connected client websockets.
- on each connect: add to the set; immediately send the current
  `protocol.state(session.snapshot())` so the new window isn't blank.
- on each message from a client: `protocol.loads` it inside a try/except
  `ProtocolError` (log and ignore bad frames), then `session.submit(msg)`.
- a background task ticks: every ~30 ms, `session.advance(30)`, then broadcast
  `protocol.state(session.snapshot())` to all clients; drop clients whose send
  fails. Stop nothing on game_over yet beyond what the engine already does.
- run on `ws://localhost:8765`.
Use `websockets.serve`. Keep the broadcast and the tick in one asyncio loop.

### `client.py` — reuse the graphical stack (marked `# pragma: no cover`)

Mirror `app.py`'s `build_game`, with two differences:

1. the `Controller` is built with a `ClientProxy(send)` instead of the real
   `GameEngine`, where `send` puts a message on the websocket.
2. the frame loop does NOT tick a clock or call a local engine. It:
   - keeps the latest snapshot received from the server (start with `None`;
     draw nothing/"connecting" until the first arrives),
   - on each frame draws that snapshot with the EXISTING `renderer` and `panel`,
   - forwards mouse clicks to the `Controller` exactly as `app.py` does.
   A background asyncio task receives messages, `protocol.loads` +
   `protocol.decode_snapshot` on `state` messages, and stores the snapshot for the
   draw loop. Bridge the asyncio receive loop and the OpenCV loop simply (a
   thread or `asyncio` + `cv2.waitKey` poll) — keep it minimal and DO NOT block
   the draw loop on the network (mentor: never freeze the graphics thread).
`renderer.render(snapshot, elapsed_ms)` needs an elapsed-ms value for animation.
The client has no clock of its own now, so use a local wall-clock stopwatch purely
for animation timing (e.g. `time.time()` since start) — animation timing is
cosmetic and independent of game time, which comes from the server. Note this
choice in a comment.

---

## STOP after Step 3

When `.\check.ps1 -Full` is green (session + proxy tests included, still 100% on
the non-`pragma` code), and you have manually confirmed two client windows mirror
each other through the server, commit:

`feat: single-process server + minimal client over WebSocket (Step 3)`

Then STOP. Do not start colour assignment / login (Step 4).
 