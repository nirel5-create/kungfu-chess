# Step 6 — put the bus to work (slide 1)

Slide 1 asks for two things: *"Implement pub/sub bus"* and *"Use the bus for:
Update Scores · Update Move Logs · Adding sound · Game start/end animations."*

The first half was done in Step 1 — `common/bus.py`, 16 tests. **The second half
was never done.** `common.bus` is imported by nothing except its own test file.
This step closes that, and with it two checklist items: *Event bus publishes game
events* and *Bus events are forwarded to clients when needed.*

---

## IRON RULES

1. **Never modify an existing test.** All 382 must still pass.
2. **Never edit** `engine/`, `model/`, `rules/`, `realtime/`, `boardio/`,
   `texttests/`, **`view/`**, `input/`, `main.py`. `GameObserver` and
   `ScorePanel` are frozen — they become subscribers **without being changed**.
3. **`app.py` must keep working exactly as it does now.** It has no bus and no
   sound; that is fine and must stay true.
4. **Code and comments in English**, American spelling.
5. **New/edited files: CRLF with a final newline.**
6. `.\check.ps1 -Full` green before committing.
7. **Do not** implement Rooms, countdown, ELO, passwords or file logging.

---

## Where the bus lives, and why the client

All four uses on slide 1 are things a **player sees or hears**. `GameObserver`
and `ScorePanel` already exist in `view/` — the client side. So the bus is the
client's internal fan-out.

**And note what the server does *not* do:** it sends full snapshots, not events
(`Server_Design.md` section 2). So the client **derives** events by comparing
each snapshot to the previous one. That is consistent, not a workaround: whoever
wants events computes them from state, on the side that is looking.

```
network thread ──► snapshot ──► bus.publish(SNAPSHOT)
                                     │
              ┌──────────────────────┼──────────────────────┐
              ▼                      ▼                      ▼
        GameObserver           event detector          (future subscribers)
        (score, log)           publishes SOUND,
                               GAME_START/END
                                     │
                          ┌──────────┴──────────┐
                          ▼                     ▼
                    sound player           overlay animation
```

**The test of whether this worked:** adding a sound must not require editing the
draw loop. If it does, the bus is not earning its place.

---

## Current draw loop, for reference

```python
observer.observe(snapshot, elapsed_ms)
frame = renderer.render(snapshot, elapsed_ms)
panel.draw(frame)
cv2.imshow(_WINDOW, frame.img)
```

Three direct calls. After this step the loop publishes once and draws; it stops
naming who reacts.

---

## 1. `client/events.py` — derive events from consecutive snapshots

New package `client/` (with `__init__.py`), because `client.py` is already long
and these parts are pure and testable while `client.py` is not.

> If a module named `client.py` and a package named `client/` cannot coexist in
> this layout, check it before writing and report — do not silently rename
> `client.py`, which is the documented entry point. A `clientside/` package is
> an acceptable fallback; say which you chose and why.

**What it owns:** turning two consecutive snapshots into the events slide 1
needs.
**What it does NOT own:** playing sound, drawing, sockets, or scoring (that is
`GameObserver`'s, and it stays untouched).

```python
class GameEventSource:
    def __init__(self, bus): ...
    def on_snapshot(self, snapshot): ...   # subscribe this to topics.SNAPSHOT
```

### What it publishes, and how each is detected

| topic | payload | detected by comparing to the previous snapshot |
|---|---|---|
| `GAME_START` | `{}` | the first snapshot ever seen |
| `SOUND` | `{"name": "move"}` | some piece's `(row, col)` changed |
| `SOUND` | `{"name": "capture"}` | a piece present before is absent now |
| `SOUND` | `{"name": "promotion"}` | a piece at the same cell changed `kind` |
| `SOUND` | `{"name": "game_over"}` | `game_over` went `False` → `True` |
| `MOVE_LOG` | `{}` | same trigger as `move`/`capture` — "the log may have changed" |
| `SCORE_UPDATE` | `{}` | same trigger as `capture` |
| `GAME_END` | `{"winner": ...}` or `{}` if not derivable | `game_over` went `False` → `True` |

Rules:
- **Publish each event at most once per snapshot**, even if several pieces moved
  in the same frame. Snapshots arrive ~30/sec and a single move spans many
  frames, so a per‑frame `move` sound would fire dozens of times for one move.
  **Detect the transition, not the state.** This is the single most important
  behaviour in this module — get it wrong and the sound is unusable.
- `GAME_START` and `GAME_END` publish **exactly once each** per source instance.
- With no previous snapshot, publish only `GAME_START`.
- A `capture` takes precedence over `move` when both happened in one frame —
  one sound per frame, and the capture is the more informative one.

**On the overlap with `GameObserver`:** the observer also notices vanished
pieces, for scoring. This module notices them for sound. That is a small
duplication of a two-line diff, and the alternative — routing sound through the
observer — would give the score keeper a second, unrelated job. Note the
trade‑off in a comment rather than leaving a reader to wonder.

### Tests — `tests/unit/test_events.py`

Use a real `Bus` and record published payloads. Build snapshots with
`GameSnapshot`/`PieceView` directly, or from a tiny real engine.

1. the first snapshot publishes `GAME_START` and nothing else
2. an identical second snapshot publishes no sound at all
3. a piece changing cell publishes `SOUND` `"move"` once
4. **the same move still in progress over three consecutive snapshots publishes
   `"move"` only once** (the transition test — the important one)
5. a piece vanishing publishes `SOUND` `"capture"`
6. a capture also publishes `SCORE_UPDATE`
7. a piece changing `kind` at the same cell publishes `SOUND` `"promotion"`
8. `game_over` flipping publishes `SOUND` `"game_over"` and `GAME_END`
9. `game_over` staying true does **not** publish `GAME_END` again
10. `GAME_START` is published only once even after many snapshots
11. a frame with both a capture and a move publishes only `"capture"`

---

## 2. `client/sound.py` — play a named sound

```python
class SoundPlayer:
    def __init__(self, folder, play=None, names=None): ...
    def on_sound(self, payload): ...   # subscribe this to topics.SOUND
```

- `play` is **injected**, defaulting to the real Windows player. Same pattern as
  `ClientProxy(send)`, `GameRegistry(make_session)` and `db.connect(connector=)`.
  This is what makes it testable with no audio hardware, and it is why there is
  no monkeypatching anywhere in this project.
- The real player uses `winsound.PlaySound(path, SND_FILENAME | SND_ASYNC)`.
  **`SND_ASYNC` matters twice:** it does not block the draw loop, and starting a
  new sound replaces the one still playing. The provided files are ~2 s long and
  moves happen about every 2 s, so without replacement they would pile up.
  Import `winsound` **locally inside the real player**, not at module top, so the
  module imports on a non‑Windows machine (the test environment) — the same
  reason `view/sprite_library.py` imports `cv2` locally.
- An unknown name, or a missing file, is **logged and ignored** — never raised. A
  missing sound must not take down the game.

**Sound files:** put the supplied `.wav` files in `assets/sounds/`. Four have a
real trigger: `move`, `capture`, `promotion`, `game_over`.

`illegal_move.wav` has **no trigger** and must not be wired up: the server
silently ignores an illegal command and sends no rejection, so the client cannot
know. Say this in a comment — it is a real gap, and adding it later would mean a
new `error` message from the server plus one more `subscribe` here, with no
change to anything else. That is the bus paying off.

### Tests — `tests/unit/test_sound.py`
1. a known name calls `play` with the matching file path
2. an unknown name does not call `play` and does not raise
3. a missing file does not call `play` and does not raise
4. `on_sound` reads the name out of the payload dict
5. a payload with no `"name"` key does not raise

---

## 3. `client/overlay.py` — the start/end animation

Keep it modest and honest: the renderer is frozen, so this draws **on top of**
the finished frame.

```python
class BannerOverlay:
    def __init__(self, duration_ms=2000): ...
    def on_game_start(self, payload): ...
    def on_game_end(self, payload): ...
    def draw(self, frame, elapsed_ms): ...   # no-op when nothing is showing
```

Shows a short banner ("GO" on start, "GAME OVER" on end) for `duration_ms`, then
stops. Draw with `Img.put_text`, which already exists. Keep the state machine
pure — a test can assert what is showing at a given `elapsed_ms` without drawing
anything.

### Tests — `tests/unit/test_overlay.py`
1. nothing shows before any event
2. after `on_game_start`, a banner shows
3. the banner stops after `duration_ms` has elapsed
4. `on_game_end` shows its own banner
5. `draw` on a fresh overlay does not touch the frame

---

## 4. `client.py` — publish once, draw a list

In `build_client`: create one `Bus`, and subscribe

- `GameObserver.observe` — via a tiny lambda supplying `elapsed_ms`, since
  `observe` takes two arguments and the bus passes one payload. **Do not change
  `GameObserver`.**
- `GameEventSource.on_snapshot` → `topics.SNAPSHOT`
- `SoundPlayer.on_sound` → `topics.SOUND`
- `BannerOverlay.on_game_start` / `on_game_end`

The draw loop becomes:

```python
bus.publish(topics.SNAPSHOT, snapshot)      # everyone reacts
frame = renderer.render(snapshot, elapsed_ms)
for overlay in overlays:                     # panel and banner both draw here
    overlay.draw(frame, elapsed_ms)
cv2.imshow(_WINDOW, frame.img)
```

`ScorePanel.draw(image)` takes one argument and `BannerOverlay.draw` takes two —
wrap the panel in a small adapter so the loop can treat every overlay the same
way. **Wrapping, not editing** — `ScorePanel` is frozen.

The point: **adding a subscriber never touches this loop.** Say so in a comment,
because that is the whole justification for the step.

Keep socket/OpenCV code `# pragma: no cover`.

---

## Verify

1. `.\check.ps1 -Full` — 382 + new tests, 100% on non‑pragma code, pylint 10/10
   (`check.ps1` lints `common server.py client.py`; **add the new `client/`
   package to that list**), fuzz clean.
2. `python app.py` — unchanged, no sound, no bus.
3. `docker compose up -d --build`, two clients:
   - a banner on start
   - a **move** sound once per move, not a stutter of dozens
   - a different sound on capture
   - a sound and a banner on king capture
   - score and move log still update as before
4. Confirm `git grep -l "common.bus\|common import bus"` now lists real modules,
   not only `tests/unit/test_bus.py`.

## STOP after Step 6

Commit as `feat: wire the pub/sub bus into the client for scores, move log, sound and animations (Step 6)`
and stop.
