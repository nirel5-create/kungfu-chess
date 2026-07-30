# Step 5 — game registry: many games, each with a lifecycle

## Why this step exists

A bug found by testing: the server builds **one** `GameSession` at startup and
keeps it forever. Once a king is captured that session stays `game_over`
permanently, so every client that connects afterwards receives a finished game
and closes immediately. The product cannot be demonstrated twice without
restarting the container.

The bug is a symptom, not the disease. The server treats the game as *"the
server's game"*, but slides 5 and 6 both assume a game is **its own entity**:
`Play` matches strangers into **a** game, `Room` lets people join **a** room. A
server holds **many** games.

So this step introduces the missing abstraction. It is the `Game Allocator`
boundary from `Server_Design.md`: *who decides which game you sit in.*

**And it must be built so that `Play`, `Room`, the 20-second countdown and ELO
are all added as new code, never as edits to this.** If adding `Room` later
forces a change here, this design is wrong.

---

## IRON RULES

1. **Never modify an existing test.** All 362 must still pass.
2. **Never edit** `engine/`, `model/`, `rules/`, `realtime/`, `boardio/`,
   `texttests/`, `view/`, `input/`, `main.py`.
3. **`app.py` must keep working exactly as it does now.**
4. **Code and comments in English**, American spelling (`color`).
5. **New/edited files: CRLF with a final newline.**
6. `.\check.ps1 -Full` green before committing.
7. **Do not** implement `Play`, `Room`, the countdown, ELO, passwords or file
   logging. This step only builds the thing they will attach to.

---

## The shape

```
   server.py            asks: which game does this connection belong to?
        |
        v
   GameRegistry         id -> (GameSession, seats)   + lifecycle
        |
        v
   GameSession          one engine, ownership check   (already exists)
```

Three responsibilities, kept apart on purpose:

| who | decides |
|---|---|
| **policy** (a small function the server calls) | *which* game you join |
| **GameRegistry** | games exist, seats, lifecycle |
| **GameSession** | commands, ownership, time |

`Play` and `Room` are later replacements for **policy only**. That is the whole
reason policy is not inside the registry.

---

## 1. `common/registry.py` — new module

Pure: no asyncio, no sockets, no wall clock. Time is explicit, exactly as
`GameSession.advance(ms)` already is, so behaviour is deterministic and testable.

**What it owns:** which games exist, who sits in which seat of which game, and
what happens to a game after it ends.
**What it does NOT own:** how a player is matched to a game, sockets,
broadcasting, rating arithmetic, or the passage of real time.

### Required API

```python
GAME_END_LINGER_MS = 3000     # how long a finished game stays before removal

class GameRegistry:
    def __init__(self, make_session, bus=None): ...
    def create(self, game_id=None): ...          # -> game_id
    def join(self, game_id, username): ...        # -> "w" | "b" | "viewer"
    def leave(self, game_id, username): ...       # -> None
    def color_of(self, game_id, username): ...    # -> color or None
    def session(self, game_id): ...               # -> GameSession or None
    def game_ids(self): ...                       # -> tuple of ids
    def advance(self, ms): ...                    # tick every game + lifecycle
```

### Behaviour, exactly

**`__init__(make_session, bus=None)`**
`make_session` is a zero-argument callable returning a fresh `GameSession`. It
is **injected**, not imported — the registry must not know how a board or an
engine is built, which is what lets tests hand it a tiny 1×3 board. `bus` is an
optional `common.bus.Bus`; when present the registry publishes lifecycle events
(see below). When absent nothing is published and everything else is unchanged.

**`create(game_id=None)`**
Creates a game with a fresh session. When `game_id` is `None`, generate one
(a short unique string). When given, use it as-is — this is what `Room` will
need later, because a room's id **is** its name (slide 6). Creating an id that
already exists must raise `ValueError`; silently replacing a live game would
drop the games inside it.

Publish `topics.GAME_START` with `{"game_id": ...}`.

**`join(game_id, username)`**
- Unknown `game_id` → raise `KeyError`.
- **If this username already has a seat in this game, return that same seat.**
  This is what makes reconnecting work: leaving does not erase the seat, so
  coming back gets the same color. Note in a comment that the *timed* part of
  reconnection (a 20-second window, then forfeit) is a later step, and that
  this step deliberately only makes the seat *stable*, not *expiring*.
- Otherwise assign the first of `"w"`, `"b"` not already held by some username
  in this game; if both are held, return `"viewer"`.
- Track the username as connected.

**`leave(game_id, username)`**
Marks the username as not connected. **Does not free the seat.** Unknown game or
unknown username is a no-op, never an error — a disconnect can arrive after a
game has already been removed, and that is normal, not exceptional.

**`color_of(game_id, username)`**
The seat, or `None` if that username has no seat here or the game is gone.
`server.py` uses this to pass a color into `GameSession.submit`.

**`advance(ms)`**
1. Call `advance(ms)` on every live game's session.
2. For any game that has just become `game_over` **for the first time**:
   publish `topics.GAME_END` with
   `{"game_id": ..., "winner": <"w"|"b"|None>, "seats": {username: color, ...}}`
   and start its linger timer. Publish exactly **once** per game.
3. Remove any game whose linger timer has run past `GAME_END_LINGER_MS`.

**Why linger rather than removing at once:** the players must see the final
position and the game-over state. Removing the game the instant the king falls
would blank their screens before they know what happened. Three seconds is
enough to see it and short enough not to hold memory.

**Why publish instead of writing to the database:** the registry does not know
what a rating is. It announces the result and moves on; whoever cares
subscribes. That is the same `write-behind` split `Server_Design.md` argues for
when Postgres is down — and it is what lets ELO be added later as a subscriber,
with **no change to this file**.

### Determining the winner

`GameSession` exposes `game_over` but not who won. Derive the winner from the
snapshot: the color whose king is **still on the board** wins; if neither or
both kings are present, the winner is `None`. Use `Config.king_type` rather
than a hardcoded `"K"` — the king piece is configurable and hardcoding it is
exactly what the mentor cites as the kind of rigidity to avoid. Read it from
the session's own config if reachable; otherwise take it as a constructor
argument with a sensible default and say so in a comment. **Check what is
actually reachable before writing this — do not assume.**

### Tests — `tests/unit/test_registry.py`

Use a fake `make_session` where useful, and a real tiny engine where the test is
about game-over. Use a real `Bus` and record what it publishes — not a mock.

1. `create()` returns an id, and `game_ids()` contains it
2. `create(game_id="cocorico")` uses that exact id
3. `create` with a duplicate id raises `ValueError`
4. first `join` gets `"w"`, second `"b"`, third and fourth `"viewer"`
5. `join` with a username that already has a seat returns the same color
6. `leave` then `join` with the same username returns the same color again
7. `leave` then `join` with a **different** username does **not** get the
   vacated color (it is still held)
8. `leave` on an unknown game or unknown username does not raise
9. `join` on an unknown game raises `KeyError`
10. `color_of` returns the seat, and `None` for a stranger
11. `session(unknown_id)` returns `None`
12. `advance` ticks every game (two games, both progress)
13. on king capture, `GAME_END` is published once with the right winner and seats
14. `GAME_END` is **not** published a second time on further `advance` calls
15. a finished game is still present before `GAME_END_LINGER_MS` has elapsed
16. a finished game is gone after `GAME_END_LINGER_MS` has elapsed
17. `GAME_START` is published on `create`
18. with `bus=None`, nothing raises and lifecycle still works

---

## 2. `server.py` — use the registry

Replace the single module-level session.

**Connection state** becomes `websocket -> (game_id, username)`.

**The join policy for this step** — a small named function, so it is obvious
what `Play` and `Room` will later replace:

```python
def _find_or_create_game(registry):  # pragma: no cover
    """This step's placeholder policy: everyone shares one open game, and a
    new one is created when none is open. Play (slide 5) and Room (slide 6)
    replace THIS FUNCTION and nothing else -- which is the point of keeping
    it separate from GameRegistry."""
```

An "open" game means one that exists and is not `game_over`. If there is none,
`create()` a new one. **This is what fixes the reported bug:** a finished game
is no longer handed to a new arrival.

**On connect:** read the login username (already implemented), pick a game via
the policy, `registry.join(...)`, send `protocol.assigned(color)`, then the
first `state`.

**On message:** `color = registry.color_of(game_id, username)`, then
`registry.session(game_id).submit(message, color)`. If the game is gone
(`session` is `None`), ignore the message — do not crash.

**On disconnect:** `registry.leave(game_id, username)`.

**Tick loop:** call `registry.advance(_TICK_MS)` once, then broadcast each
game's snapshot **only to the clients sitting in that game**. Today every
client shares one game; once `Room` exists they will not, and broadcasting
per-game now means `Room` needs no change here either.

**Bus:** create one `Bus` and pass it to the registry, so `GAME_START` and
`GAME_END` are already being published. Nothing subscribes yet — that is
honest, and it is the hook ELO will use. Say so in a comment.

Keep socket-level code `# pragma: no cover`.

---

## Verify

1. `.\check.ps1 -Full` — 362 + new tests, 100%, pylint 10/10, fuzz clean.
2. `python app.py` unchanged.
3. `docker compose up -d --build`, two clients, play a game to **king capture**.
   Both see the game end.
4. **Close both clients, open two new ones — a fresh game starts.** This is the
   bug that prompted the step.
5. Close one client and reopen it with the **same username** — same color back.
6. Open it with a **different** username while the seat is held — becomes a
   viewer, not the vacated color.

## STOP after Step 5

Commit as `feat: game registry with per-game lifecycle, replacing the single global session (Step 5)`
and stop.
