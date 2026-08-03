# Step 10 — Play: matchmaking by rating (slide 5.1)

Slide 5: *"Add 'Play' Button: Finds the other player with ELO in range of +-100
that also seeks for a game. If doesn't find - waits for 1 min, if can't find -
pops up a message that can't find."*

This is the first half of slide 5; the disconnect countdown is the second and is
Step 9. Together they close slide 5, and with slide 4 already done, **every
slide requirement is implemented.**

---

## What already exists (verified — do not rebuild)

- **The whole protocol is already there.** `protocol.PLAY`, `protocol.play()`,
  `protocol.MATCHMAKING`, `protocol.matchmaking(status)`, and its docstring
  already defines the exact three states: `"searching"`, `"found"`, `"timeout"`,
  with `"found"` meaning an `assigned` follows. Written on day one; use it as-is.
- **The client already sends `protocol.play()`** when the player picks Play in
  the dialog. The server currently ignores it and falls back to the shared game.
- **`db.get_rating(conn, username)`** already returns a player's rating.
- `GameRegistry.create()` already makes a game with a generated id — which is
  exactly what a matched pair needs.

**So this step is a queue and a policy. If you find yourself changing
`GameRegistry` or `protocol.py`, stop and re-read them first.**

---

## IRON RULES

1. **Never modify an existing test.**
2. **Never edit** `engine/`, `model/`, `rules/`, `realtime/`, `boardio/`,
   `texttests/`, `view/`, `input/`, `main.py`.
3. **`app.py` must keep working exactly as it does now.**
4. **Code and comments in English**, American spelling.
5. **CRLF with a final newline** on every new/edited file.
6. `.\check.ps1` (fast) must pass before `-Full`.
7. **No monkeypatching** anywhere — inject collaborators, as the rest of this
   codebase does.

---

## 1. `common/matchmaker.py` — the queue, pure

No sockets, no database, no wall clock. Time is explicit, exactly as
`GameSession.advance(ms)` and `GameRegistry.advance(ms)` already are — that is
what makes the one-minute rule testable without waiting a minute.

**What it owns:** who is waiting, at what rating, for how long, and which two of
them should be paired.
**What it does NOT own:** creating games, reading ratings from a database,
sending messages, or knowing what a websocket is.

```python
RATING_WINDOW = 100      # slide 5: an opponent within +-100
SEARCH_TIMEOUT_MS = 60000  # slide 5: give up after one minute

class MatchMaker:
    def __init__(self, window=RATING_WINDOW, timeout_ms=SEARCH_TIMEOUT_MS): ...
    def enqueue(self, username, rating): ...   # -> None
    def cancel(self, username): ...            # -> None, no-op if absent
    def advance(self, ms): ...                 # -> (pairs, timed_out)
    def waiting(self): ...                     # -> tuple of usernames, for logging
```

### Behaviour, exactly

**`enqueue`** — adds a seeker with their rating and a wait counter at 0. The
same username enqueued twice must not appear twice; treat the second call as a
no-op rather than an error, since a client can retry.

**`advance(ms)`** — in one pass:
1. add `ms` to every seeker's wait counter
2. pair whoever can be paired
3. return `(pairs, timed_out)`, where `pairs` is a list of `(user_a, user_b)`
   and `timed_out` is a list of usernames whose wait passed `timeout_ms`
4. everyone returned — paired or timed out — leaves the queue

**Pairing rule:** two seekers may pair only if `abs(rating_a - rating_b) <=
window`. When several pairings are possible, **pair the closest ratings first** —
that is the point of a rating window, and "first two in the list" would make the
window meaningless whenever three or more are waiting. Say so in a comment.

**Order of operations matters:** a seeker whose time expires *in the same call*
in which they could be paired should be **paired, not timed out**. Finding a game
is the desired outcome; make this explicit in code and say why.

### Tests — `tests/unit/test_matchmaker.py`

1. one seeker alone is never paired
2. two seekers within the window are paired
3. two seekers outside the window are not paired
4. a paired seeker leaves the queue
5. with three seekers, the closest pair is chosen, not the first two
6. `advance` past `timeout_ms` reports the seeker as timed out
7. a timed-out seeker leaves the queue
8. a seeker just under the timeout is neither paired nor timed out
9. `cancel` removes a seeker; a later `advance` reports nothing for them
10. `cancel` on an unknown username does not raise
11. enqueuing the same username twice does not duplicate them
12. a seeker who could be paired **and** has just timed out is paired, not timed out
13. a custom `window` and `timeout_ms` are honoured

---

## 2. Server — wire it in

**On a `play` message:** look up the sender's rating with `db.get_rating`, and
enqueue them. Reply `protocol.matchmaking("searching")` so the player knows the
search started. **If the database is unreachable, use `db.DEFAULT_RATING`** and
log it — the same promise the rest of the server keeps: play continues without
Postgres.

**In the tick loop:** call `matchmaker.advance(tick_ms)` once per tick.
- For each pair: `registry.create()` a fresh game, `join` both, send each
  `protocol.matchmaking("found")` and then `protocol.assigned(color)`, in that
  order — the protocol docstring promises `assigned` follows `found`.
- For each timeout: send `protocol.matchmaking("timeout")`.

**A seeker who disconnects while queued must be removed** — `cancel` them on
disconnect, or a pairing will be created for someone who is gone. This is the
same class of bug as the abandoned-game one; do not repeat it.

Log every enqueue with the rating, every pair with both usernames and ratings,
and every timeout.

---

## 3. Client — searching, found, and the timeout message

Today Play sends `protocol.play()` and then opens the window. Now it must wait
for the outcome:

- On `matchmaking:searching` — show that a search is in progress. The player must
  not be left staring at nothing for up to a minute.
- On `matchmaking:found` — carry on into the game as usual; `assigned` follows.
- On `matchmaking:timeout` — **slide 5 explicitly asks for a message box.** Use
  the same OS-dialog approach `roomdialog.py` already uses (`tkinter`), not text
  in the terminal and not something drawn in the OpenCV window. Then exit
  cleanly.

Keep it simple: a modal wait is acceptable here because the player has chosen to
wait for an opponent and has nothing else to do until one is found.

---

## Verify by eye

1. `.\check.ps1` fast, then `-Full`.
2. `python app.py` unchanged.
3. `docker compose down && docker compose up -d --build`.
4. **One client picks Play** → sees that it is searching, and after a minute gets
   a message box saying no opponent was found.
5. **Two clients pick Play** within a minute of each other → both are matched
   into the same fresh game, one white, one black, and can play.
6. Play to king capture and confirm both ratings update in `logs/server.log`.
7. **A third client picks Play while two are already playing** → it waits; it is
   not dropped into the running game.
8. Create/Join for rooms still work exactly as before.

## STOP after Step 10

Commit as `feat: Play matchmaking within +-100 rating (slide 5)` and stop.
