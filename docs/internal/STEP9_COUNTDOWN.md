# Step 9 — disconnect countdown and auto-resign (slide 5.2)

Slide 5: *"If player disconnected - auto-resign after 20 sec. Make a 'count
down' on the screen."*

This is the second half of slide 5. The first half — Play with ELO matchmaking —
is a separate step.

---

## What already exists (verified — do not rebuild)

`common/registry.py`'s `_Game` already holds everything this needs:

```python
self.seats     = {}       # username -> "w" | "b" | "viewer"
self.connected = set()    # usernames currently connected
self.ended     = False
self.linger_ms = 0        # ms accumulated since ended became True
```

- `leave()` already removes a username from `connected` **while keeping the
  seat**, which is exactly what a reconnect window requires. Its docstring says
  the timed part is a later step — this is that step.
- `join()` already returns the same seat to a returning username.
- `advance(ms)` already accumulates time per game (`linger_ms`), so counting
  elapsed milliseconds per game is an established pattern here, not a new one.
- `GAME_END` is already published with `{game_id, winner, seats}`, and the ELO
  subscriber already updates ratings from it — so **an auto-resign that ends the
  game the normal way updates ratings for free.**

**If you find yourself adding a clock, a thread, or `time.time()` anywhere in
`registry.py`, stop.** Time in this module is explicit and passed into
`advance(ms)`, which is what makes it deterministic and testable.

---

## IRON RULES

1. **Never modify an existing test.** All ~473 must still pass.
2. **Never edit** `engine/`, `model/`, `rules/`, `realtime/`, `boardio/`,
   `texttests/`, `view/`, `input/`, `main.py`.
3. **`app.py` must keep working exactly as it does now.**
4. **Code and comments in English**, American spelling.
5. **CRLF with a final newline** on every new/edited file.
6. `.\check.ps1` (fast) must pass before `-Full`.
7. **Do not** implement Play/ELO matchmaking or the joiner's move history.

---

## 1. `common/registry.py` — the countdown

```python
DISCONNECT_GRACE_MS = 20000    # slide 5: auto-resign 20 seconds after a disconnect
```

Add to `_Game`:

```python
self.away_ms = {}   # username -> ms disconnected so far, for SEATED players only
```

### Behaviour

**`leave(game_id, username)`** — as now, plus: if that username holds `"w"` or
`"b"`, start its countdown at 0. **A viewer leaving starts nothing** — a
spectator walking away is not a forfeit, and the slide's rule is about players.

**`join(...)`** — a returning username clears its `away_ms` entry. Say in a
comment that this is what makes the reconnect window real rather than nominal.

**`advance(ms)`** — for each live, not-yet-ended game, add `ms` to every entry in
`away_ms`. When an entry reaches `DISCONNECT_GRACE_MS`:

- the **opponent wins**; end the game the same way a king capture does, so one
  path ends games and ratings update through the existing `GAME_END` subscriber
- publish `GAME_END` with `winner` set to the **remaining** player's color, and
  the same `seats` payload as today
- if **both** players are away past the grace period, the winner is `None` — a
  game nobody was present for is not counted, consistent with the rule already
  documented in `Server_Design.md`
- publish exactly once, and let the existing linger-then-remove logic take over

**Ordering matters:** a game that is already `ended` must not then auto-resign,
and a countdown that expires in the same `advance` call as a king capture must
not double-publish. Make the precedence explicit in code and say why in a
comment.

### A new query the server needs

```python
def countdown_ms(self, game_id):
    """Remaining ms before each away player forfeits: {username: ms_left}.
    Empty when nobody is away. The server broadcasts this so the opponent
    can see the count on screen."""
```

### Tests — add to `tests/unit/test_registry.py`

1. `leave` by a seated player starts a countdown; `countdown_ms` reports it
2. `leave` by a **viewer** starts nothing
3. `advance` reduces the remaining time
4. re-joining before the grace period clears the countdown entirely
5. reaching the grace period publishes `GAME_END` with the **opponent** as winner
6. both players away past the grace period gives `winner=None`
7. a game already ended by king capture does **not** also auto-resign
8. `GAME_END` is published exactly once
9. after auto-resign the game is removed once the linger period elapses
10. `countdown_ms` on an unknown game returns an empty mapping, not an error

---

## 2. Protocol and server

`protocol.COUNTDOWN` and `protocol.countdown(seconds)` **already exist** — check
before adding anything.

Each tick, for every game with an away player, broadcast the countdown to that
game's connected clients. **Send whole seconds, not milliseconds**, and only when
the second changes — a message 33 times a second for a number that changes once a
second is waste, and the same reasoning already governs the state broadcast.

Log the disconnect, each countdown start, and the auto-resign with its winner.

---

## 3. Client — show the count

On a `COUNTDOWN` message, store the seconds and draw them prominently — the
opponent has vanished and the game is about to be decided without a move, so
this must be impossible to miss. Draw it over the board, not in the side panel.

Clear it when a `STATE` arrives with no countdown, i.e. when the opponent
returns.

Reuse `BannerOverlay`'s pattern rather than inventing a second overlay
mechanism: it already draws over the frame and already has a readable backing
box from the GAME OVER fix.

---

## Verify by eye

1. `.\check.ps1` fast, then `-Full`.
2. `python app.py` unchanged.
3. `docker compose up -d --build`, two players in a room.
4. **Close one client.** The other must show a visible count from 20 down.
5. **Reopen it with the same username before the count ends.** The countdown
   disappears and play continues, same colour.
6. Let it run out. The remaining player wins, both see the game end, and
   `logs/server.log` shows a rating update — the winner up, the loser down.
7. Close **both** clients mid-game and confirm the log shows the game ended with
   no winner and **no** rating change.
8. Confirm a viewer leaving starts no countdown at all.

## STOP after Step 9

Commit as `feat: disconnect countdown and auto-resign (slide 5)` and stop.
