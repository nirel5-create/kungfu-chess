# Step 11 — four things the player cannot currently see or do

All four came out of manual testing, and all four are the same theme: **the
player is missing information the server already has.**

---

## What already exists (verified — do not rebuild)

- `GameObserver.__init__(config, white_name="Player 1", black_name="Player 2")`
  **already takes real names**, and its docstring says in as many words: *"a
  caller can pass real names."* Built for this.
- `GAME_END` already carries `seats` — a `{username: color}` map — and it is
  already used for ELO and for the winner's name. **Both player names are
  already known server-side.**
- `GameObserver` is **completely pure**: it imports only `collections`, no
  OpenCV, no clock. Its own docstring says *"Everything here is pure: no engine,
  no OpenCV, no clock."* That is what makes item 3 possible without duplicating
  anything.
- `sanitize_for_filename` already exists in `client.py` for log filenames.

---

## IRON RULES

1. **Never modify an existing test.**
2. **Never edit** `engine/`, `model/`, `rules/`, `realtime/`, `boardio/`,
   `texttests/`, **`view/`**, `input/`, `main.py`. `GameObserver` and
   `ScorePanel` stay frozen; wrap or configure them, never edit them.
3. **`app.py` must keep working exactly as it does now.**
4. **Code and comments in English**, American spelling.
5. **CRLF with a final newline** on every new/edited file.
6. `.\check.ps1` (fast) must pass before `-Full`.
7. **No monkeypatching.** Inject collaborators, as this codebase already does.

---

## 1. Reject a duplicate username at login, not after the dialog

**Found in testing:** a player disconnected as `2`, logged back in as `1` while
`1` was still connected, **was shown the room dialog**, filled it in, and only
then got `already_connected` and was closed.

**Why it happens:** the check lives in `GameRegistry.join`, and joining happens
only after the room choice is known — i.e. after the dialog. The server cannot
know any earlier, because it does not yet know which game.

**The fix, and why it is also more correct:** a username is **one person**. If
`1` is already connected it does not matter which room they are trying to enter.
So the check belongs to the server ("who is connected to me") rather than to a
game ("who is seated here"). Track connected usernames at server level and
refuse at login, before `_read_room_choice` is ever called, exactly as
`bad_password` already does.

Keep `GameRegistry`'s own per-game check as it is — it is still correct, and
still the right guard at that layer. This adds an earlier one, it does not move
it.

Remove the username from the server-level set on disconnect, including when the
connection drops abnormally. **A leak here locks a player out of their own
account until the server restarts**, so make sure it is in the same `finally`
that already calls `registry.leave`.

### Tests
- a second login under a connected username is refused at login
- the refusal happens without any room choice being read
- after that username disconnects, a fresh login succeeds
- an abnormal disconnect still frees the name

---

## 2. Reject names that cannot be displayed

**Found in testing:** nothing stops a username or room name containing emoji.
`cv2.putText` **cannot render them** — they appear as boxes or garbage in the
score panel and the room indicator.

Add one shared validator (in `common/`, since both the server and the dialog
need it):

```python
def is_displayable(name): ...   # -> bool
```

- Accept letters, digits, spaces, `-` and `_`.
- **Keep inner spaces** — `normalize_room_name` already preserves them
  deliberately, and "my room" is a reasonable room name.
- Reject anything `cv2.putText` cannot draw, and anything empty after stripping.
- Cap the length so a long name cannot overflow the panel; pick a limit that
  fits and say what it is.

Apply it in **both** places:
- **The room dialog**, before sending: show the problem in the dialog and let
  the player correct it, rather than sending something the server will reject.
- **The server**, on login and on room create/join: a client is not trusted, so
  the server validates too, and replies `protocol.error` with a clear reason.

Do not reuse `sanitize_for_filename` for this. That one *rewrites* a name to be
safe on disk; this one *rejects* a name the player must fix. Different jobs —
silently rewriting a display name would be worse than refusing it.

---

## 3. A joining or reconnecting player sees the move log from the start

**Found in testing:** a player who reconnects gets an **empty** score panel and
move log, because `GameObserver` builds them by diffing the snapshots **it** has
seen, and a new window has seen none.

**The fix:** the server runs its own `GameObserver` per game — it is pure, so it
runs anywhere — fed the same snapshots the tick loop already produces. When a
client joins, and whenever the log changes, the server sends the current log and
scores. The client displays what it was sent.

**Two things this also fixes, worth saying in a comment:**
- Every client now shows the **same** log. Today each computes its own, so two
  windows could in principle disagree.
- It is consistent with everything else here: the server is the authority.

**Send on change, not per tick.** The log only changes on a capture — every few
seconds — so a per-tick broadcast would be pure waste. The countdown broadcast
already uses exactly this "send when the value changes" pattern; follow it.

**On the client**, `ScorePanel` is frozen and reads three methods —
`log()`, `score_of(color)`, `name_of(color)`. Give it a small **adapter** backed
by the server's data, exactly as `_SnapshotBoard` and `_PanelOverlay` already
do. Do not edit `ScorePanel`, and do not edit `GameObserver`.

**Viewers get it too.** A spectator who joins mid-game with no history is just as
lost as a returning player, and it costs nothing extra.

### Tests
- the adapter reports the log, scores and names it was given
- an empty payload yields an empty log and zero scores, no raise
- the server's observer accumulates across snapshots
- a client joining mid-game receives the log so far

---

## 4. Show real player names instead of Player 1 / Player 2

`GameObserver` already accepts `white_name` and `black_name`. The server knows
both from `seats`. So: include both names in the same message as item 3, and
have the client's adapter return them from `name_of`.

**Behaviour:** start as `Player 1` / `Player 2` and replace each with the real
name as that seat is taken — which is what the player asked for and what network
games normally do. A seat nobody has taken keeps its placeholder.

---

## Verify by eye

1. `.\check.ps1` fast, then `-Full`.
2. `python app.py` unchanged — still `Player 1` / `Player 2`, no server.
3. Log in as `alice`, then try `alice` again in a second window → **refused
   immediately, no room dialog appears.**
4. Close the first `alice`, log in as `alice` again → works.
5. Try a username with an emoji → refused with a readable reason.
6. Try a room name with an emoji → the dialog says so; try one with a space →
   accepted.
7. Two players, `alice` and `bob` → the panel shows **alice** and **bob**, not
   Player 1 / Player 2.
8. Take a few pieces, close one client, reopen with the same username → **the
   move log and scores are all there from the start of the game.**
9. A third client joins as a viewer mid-game → also sees the full log.

## STOP after Step 11

Commit as `feat: player-visible names, history and name validation` and stop.
