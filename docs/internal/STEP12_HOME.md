# Step 12 — the home screen (slide 3) and interface polish

Slide 3 asks for a **Home screen**. The project never built one: login is two
terminal prompts, a room dialog opens once, and from then on the player is
locked into whatever they picked until they close the window.

Every remaining interface complaint is a symptom of that one gap:

- no way to correct a typed username or password — the only escape is Ctrl-C
- no way to leave a room and create or join a different one
- no way to start another game after one ends, only Esc (the option deferred
  earlier, when the game-over banner was added)
- the mute toggle is keyboard-only, with no button to click

**One screen fixes all four.** Building them separately would mean four
half-answers to the same question: *where does a player go when they are not in
a game?*

---

## What already exists (verified — do not rebuild)

- `client/roomdialog.py` already has `ask_room()` returning
  `(action, room_name)` with `CREATE` / `JOIN` / `PLAY`, plus
  `show_no_opponent_found()`, and a **pure, tested** `normalize_room_name`.
- `_prompt_username()` and `_prompt_password()` already exist in `client.py`.
- `SoundPlayer` already has a `muted` flag and a working toggle.
- The end banner already names the winner; the server already sends the outcome.

**This step reorganises the flow around these pieces. If you find yourself
rewriting `ask_room` or `SoundPlayer`, stop and reuse them.**

---

## IRON RULES

1. **Never modify an existing test.**
2. **Never edit** `engine/`, `model/`, `rules/`, `realtime/`, `boardio/`,
   `texttests/`, `view/`, `input/`, `main.py`.
3. **`app.py` must keep working exactly as it does now** — no home screen, no
   login, no server.
4. **Code and comments in English**, American spelling.
5. **CRLF with a final newline** on every new/edited file.
6. `.\check.ps1` (fast) must pass before `-Full`.
7. **No monkeypatching.** Inject collaborators, as this codebase already does.

---

## 1. The shape: a loop, not a straight line

Today `run()` is a straight line — prompt, dialog, play, exit. The home screen
makes it a loop:

```
   login  ->  HOME  ->  game  ->  back to HOME
                ^                      |
                +----------------------+
```

**Design the state machine as a pure, tested object**, separate from any window:

```python
# client/homescreen.py
LOGIN, HOME, PLAYING, QUIT = "login", "home", "playing", "quit"

class HomeFlow:
    def __init__(self): ...
    @property
    def state(self): ...
    def logged_in(self, username): ...
    def chose(self, action, room_name=""): ...   # CREATE / JOIN / PLAY / QUIT
    def game_ended(self): ...                    # -> back to HOME
    def login_refused(self, reason): ...         # -> back to LOGIN
```

**Why a separate object:** the window and the socket cannot be unit-tested, but
*"what happens after a game ends"* is exactly the kind of decision that must be.
This is the same split that already worked for `MatchMaker` and `GameRegistry`:
the decision is pure, the plumbing is `pragma: no cover`.

### Tests — `tests/unit/test_homescreen.py`
1. a fresh flow starts at `LOGIN`
2. `logged_in` moves to `HOME`
3. `login_refused` returns to `LOGIN`, keeping no stale username
4. choosing `PLAY` moves to `PLAYING`
5. `game_ended` returns to `HOME`, **not** to `LOGIN` — a player who has logged
   in stays logged in
6. choosing `QUIT` from `HOME` reaches `QUIT`
7. the chosen room name is remembered and readable while `PLAYING`
8. `game_ended` clears the room name, so the next choice starts clean

---

## 2. Login the player can correct

Replace the one-shot prompts with a loop: on `bad_password` or a rejected name,
say why and ask again, rather than exiting the process. Offer a way out — an
empty username, or a plain `q`, quits — and say so in the prompt text, since an
option nobody can discover is not an option.

Keep it in the shell: slide 3 says *"do it in a shell, not via GUI."*

---

## 3. Home: one dialog, four choices

Extend `ask_room()` rather than writing a second dialog — it already has the
text box and three buttons; this adds a fourth and a title line.

- **Create** — a new room, as today
- **Join** — an existing room, as today
- **Play** — matchmaking, as today
- **Quit** — closes cleanly

Show the logged-in username and the current rating in the dialog, so the player
can see who they are and that their rating changed. The rating is already stored
server-side; if fetching it needs a message, add one to `protocol.py` following
the existing house style.

---

## 4. After a game: return home

This is the option deferred when the end banner was built: instead of waiting
for Esc, the player returns to the home dialog and can pick again.

- Keep the final position and the winner banner on screen for a moment first —
  a game that vanishes the instant it ends is worse than one that waits.
- Then close the game window and show the home dialog again.
- **Esc must still work** and must quit outright, since that is what it does
  today and players will already expect it.

Do not tear down and rebuild the whole client between games — reuse the
connection. Reconnecting per game would make the username look like a duplicate
connection to the server's own check, which is exactly the bug fixed in Step 11.

---

## 5. A mute button that can be clicked

Draw a small button in the panel strip showing the current state, and toggle it
on click. **Keep `m` working** — a keyboard shortcut and a button are not
alternatives, they are the same action reachable two ways.

The hit test (does this click fall inside the button?) is pure arithmetic: put
it in a small tested function rather than inline in the mouse callback, which is
`pragma: no cover`.

### Tests
- a click inside the button's rectangle registers as a hit
- a click outside does not
- the hit test respects the panel's actual position, not a hardcoded one

---

## Verify by eye

1. `.\check.ps1` fast, then `-Full`.
2. `python app.py` unchanged — no home screen, no login, both sides playable.
3. Wrong password → told why, **asked again**, right password works.
4. Home dialog shows the username and rating.
5. **Create** a room, play to king capture → banner → **back at the home dialog**.
6. From there **Join** a different room → works, no reconnection needed.
7. From there **Play** → matchmaking, as before.
8. **Quit** closes cleanly; **Esc** during a game still quits outright.
9. Click the mute button → sound stops, label changes; press `m` → toggles too.
10. Play two full games without restarting the client, and confirm the server
    log shows one connection, not two.

## STOP after Step 12

Commit as `feat: home screen with login retry, replay and a mute button (slide 3)`
and stop.
