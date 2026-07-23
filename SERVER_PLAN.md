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

---

## STOP HERE

After Step 2 passes, report back with the test summary. Do **not** start Step 3
(`server/`, `client/`, WebSocket) — that spec comes after these two are reviewed.
