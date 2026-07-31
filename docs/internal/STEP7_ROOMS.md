# Step 7 — Rooms (slide 6)

Slide 6: *"Button: Room → open a windows message with text box and buttons:
Create / Join / Cancel. Create: generates a new room id, written on top of the
screen. Join: enters the room whose ID you typed. Inside a room: the second
person that joins is the Black player of the game. The following people who
join are viewers."*

And from the transcript, two things the mentor said explicitly:
- **The room id IS the room name** — *"האמת הרום איידי זה בעצם השם"*. Two rooms
  may not share a name.
- **Use a real OS window**, not a hand-drawn one — he specifically ruled out
  building a text field inside the OpenCV window because it would mean handling
  keyboard events and painting characters, *"הרבה כאב ראש יותר ממה שאנחנו צריכים"*.

---

## What already exists (verified — do not rebuild)

- `protocol.ROOM_CREATE`, `ROOM_JOIN`, `ROOM` and their builders **already
  exist** in `common/protocol.py`, with `_REQUIRED_FIELDS` entries.
- `GameRegistry.create(game_id=None)` **already accepts an explicit id** — that
  parameter exists precisely for this step.
- `server.py`'s `_find_or_create_game(registry)` is the isolated policy
  function, documented as the one thing Room replaces.

**So this step is mostly wiring, not new machinery.** If you find yourself
changing `GameRegistry`, stop and reconsider — that would mean the seam was
built wrong, and it was built for this.

---

## IRON RULES

1. **Never modify an existing test.** All 433 must still pass.
2. **Never edit** `engine/`, `model/`, `rules/`, `realtime/`, `boardio/`,
   `texttests/`, `view/`, `input/`, `main.py`.
3. **`app.py` must keep working exactly as it does now.**
4. **Code and comments in English**, American spelling.
5. **CRLF with a final newline** on every new/edited file.
6. `.\check.ps1 -Full` green before committing.
7. **Do not** implement Play/matchmaking, the disconnect countdown, passwords
   or ELO.

---

## 1. The dialog — `client/roomdialog.py`

A `tkinter` dialog, shown **after the shell username prompt and before the
OpenCV window opens**. `tkinter` ships with Python — no new dependency.

> There is no Home screen in this project: login is a terminal prompt and the
> window then opens straight into the game. So the Room dialog goes where the
> Home screen would have been — between them. Say this in the module docstring
> so the deviation from the slide reads as a considered choice, not an
> oversight.

```python
CREATE = "create"
JOIN   = "join"
CANCEL = "cancel"

def ask_room(title="Room"): ...   # -> (action, room_name)
```

- One text box labelled `room name`, and three buttons: **Create / Join /
  Cancel** — the exact three from the slide's screenshot.
- Returns `(CANCEL, "")` for Cancel, for the window's X, and for Create/Join
  pressed with an empty box. **A blank name must never reach the server.**
- Returns the name stripped of surrounding whitespace.
- The whole function is `# pragma: no cover` — it opens a real window. Keep it
  small so there is little untested code, and put anything decidable
  (validation, normalisation) in a **pure helper that is tested**:

```python
def normalize_room_name(text): ...   # -> stripped name, or "" if unusable
```

### Tests — `tests/unit/test_roomdialog.py`
Only `normalize_room_name`:
1. surrounding whitespace is stripped
2. an all-whitespace name normalises to `""`
3. an empty string normalises to `""`
4. an ordinary name is unchanged
5. inner spaces are preserved (`"my room"` stays `"my room"`)

---

## 2. Server — rooms as named games

The room id **is** the game id. That is not a shortcut: a room is exactly "a
game two specific people agreed to meet in", and `GameRegistry` already keys
games by id. Say so in a comment.

Replace the placeholder policy with three explicit ones, each small and named:

```python
def _join_or_create_room(registry, room_id): ...   # slide 6
def _find_or_create_game(registry): ...            # unchanged: no room given
```

**On `room_create`:** create a game whose id is the requested name. If that id
already exists, reply `protocol.error("room_exists")` — the mentor said two
rooms may not share a name, so a silent join would be wrong. On success reply
`protocol.room(room_id)`.

**On `room_join`:** if no game with that id exists, reply
`protocol.error("no_such_room")`. On success reply `protocol.room(room_id)`.

**Seating inside a room needs no new code** — `GameRegistry.join` already gives
`"w"` to the first, `"b"` to the second and `"viewer"` to everyone after, which
is exactly what the slide describes. Note that in a comment: it is evidence the
seam was right.

**Where this happens:** the client sends `room_create`/`room_join` as its
**second** message, right after `login`. Extend the existing login read to
accept an optional following room message; if none arrives, fall back to
`_find_or_create_game` exactly as today, so a client that skips the dialog still
works.

Log every room action — created, joined, refused and why.

---

## 3. Client — dialog, then room, then the game

In `client.py`:

- After `_prompt_username()` and before the window, call `ask_room()`.
- **Cancel** → behave exactly as today (no room message; the server puts you in
  the shared game). Cancelling must not be a dead end.
- **Create/Join** → send the matching protocol message right after `login`, and
  wait for either `room` or `error` before opening the window — the same
  pattern `_wait_for_assignment_or_error` already uses for `assigned`/`error`.
  On `error`, print the reason and exit, as with `already_connected`.
- Store the room id and **draw it at the top of the screen** — slide 6 requires
  this twice, for Create and for Join. Put it in the panel strip that
  `_widen_canvas` already adds, next to the mute indicator.

`_ServerLink` will need a `room()` accessor alongside `color()` and `error()`,
guarded by the same lock.

---

## Verify by eye

1. `.\check.ps1 -Full` — 433 + new tests, 100%, pylint 10/10, fuzz clean.
2. `python app.py` unchanged.
3. `docker compose up -d --build`, then:
   - client 1: username, **Create** room `cocorico` → id shown at the top,
     seated white
   - client 2: username, **Join** `cocorico` → same id shown, seated **black**
   - client 3: **Join** `cocorico` → **viewer**, sees the board, cannot move
   - client 4: **Join** `nosuchroom` → refused on the terminal, no window
   - client 5: **Create** `cocorico` again → refused, no window
   - client 6: **Cancel** → the ordinary shared game, exactly as before
4. Two clients in a room play a full game to king capture.

## STOP after Step 7

Commit as `feat: rooms with a real dialog, create/join/cancel (slide 6)` and
stop.
