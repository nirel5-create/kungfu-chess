# Step 4 — colour assignment and shell login

Closes gaps 2 and 3 from the requirements audit, and three checklist items at
once: *Players are assigned white/black*, *Server validates moves through
GameEngine* (only complete once ownership is enforced), and *Full two-player
demo works locally* (only true once each player controls one side).

Source: CTD 26 slide 3 — "Add Home screen with: Login with username (just for
presentation) — do it in a shell, not via GUI. Support only 2 players: first
that joins is white, second is Black."

---

## IRON RULES

1. **Never modify an existing test.** All 350 must still pass.
2. **Never edit** `engine/`, `model/`, `rules/`, `realtime/`, `boardio/`,
   `texttests/`, `view/`, `input/`, `main.py`.
3. **`app.py` must keep working exactly as it does now** — local play has no
   colour assignment and one person moves both sides. This is a real supported
   mode, not an accident.
4. **Code and comments in English**, American spelling (`color`, never
   `colour`) to match the existing codebase.
5. **New/edited files: CRLF with a final newline.**
6. `.\check.ps1 -Full` green before committing.
7. **Do not** implement rooms, matchmaking, passwords, ELO or file logging —
   they are later steps.

---

## The design decision, and why (put this in the docstrings)

Ownership is **not** a chess rule. The engine knows what is *legal*; it does not
know who is *allowed to ask*. If the engine checked colors, `app.py` would break,
because local play depends on one person moving both sides.

Ownership is also not something a client may assert. If the color travelled
inside the message, a client could edit one line and send `"color": "b"` to move
the opponent's pieces. **The server knows who you are from the connection**, not
from what you claim — the same principle as `Server_Design.md`: the client does
not decide the rules, and neither does the gateway.

So responsibility splits like this:

```
server.py     knows WHO you are      (connection -> color)
GameSession   enforces the rule      (does this piece belong to that color?)
GameEngine    decides legality       (unchanged, frozen)
```

---

## 1. `common/net.py` — the ownership check

Add a module-level constant:

```python
ANY_COLOR = "any"   # local play: ownership is not enforced
```

Change `GameSession.submit` to take a color:

```python
def submit(self, message, color=ANY_COLOR): ...
```

**The default is deliberate and serves two purposes** — state both in the
docstring:
1. Local play (`app.py` and any single-process use) is a supported mode where
   one person moves both sides, so "no owner" must be expressible.
2. The existing tests in `tests/unit/test_session.py` call `submit(message)`
   with one argument. The default keeps them passing untouched, per IRON RULE 1.

### The four possible values

| value | who | may move |
|---|---|---|
| `"w"` | the white player | white pieces only |
| `"b"` | the black player | black pieces only |
| `"viewer"` | a spectator | **nothing** |
| `ANY_COLOR` | local play | anything |

`"w"` / `"b"` / `"viewer"` are exactly the values `protocol.assigned()` already
sends. Do not introduce a second vocabulary.

### How the check works

The message names a **cell**, not a piece — so the session must first find out
who sits there. The engine is frozen and has no "piece at cell" accessor, but
`snapshot()` already carries every piece with its `color`, `row` and `col`.
Add a private helper that walks the snapshot:

```python
def _piece_color_at(self, cell):
    row, col = cell
    for piece in self._engine.snapshot().pieces:
        if piece.row == row and piece.col == col:
            return piece.color
    return None                      # empty cell
```

Note in a comment that this is the same lookup `_SnapshotBoard.piece_at` does in
`client.py` — one approach, used consistently, rather than two.

Then in `submit`:
- `color == ANY_COLOR` → apply, no check.
- `color == "viewer"` → ignore every move/jump. A viewer sends nothing; if one
  does anyway, it is dropped silently.
- `"w"` / `"b"` → look up the piece at `src` (for `move`) or `cell` (for `jump`).
  Apply only if that piece's color matches. **An empty cell is also ignored** —
  there is nothing to move, and the engine would have refused it anyway.

Do not raise on a refused command. Ignoring matches how `submit` already treats
unknown message types, and a refusal is not an error the server should crash on.

### Tests to add — `tests/unit/test_session.py`

1. with `color="w"`, a move of a white piece is applied
2. with `color="w"`, a move of a black piece is ignored (snapshot unchanged)
3. with `color="b"`, the mirror of both of the above
4. with `color="viewer"`, a move of either color is ignored
5. with `ANY_COLOR`, both colors can be moved (this is local play)
6. `submit(message)` with no color argument behaves as `ANY_COLOR`
7. a jump is subject to the same ownership check as a move
8. a move whose `src` names an empty cell is ignored, no raise

---

## 2. `server.py` — assign colors on connect

Keep a mapping from websocket connection to assigned color. On connect:

- 1st connection → `"w"`
- 2nd connection → `"b"`
- 3rd and later → `"viewer"`

Immediately send that client `protocol.assigned(color)` — before the first
`state` message, so the client knows its role from the outset.

On disconnect, free the seat: remove the connection from the mapping so a
reconnecting player can take the empty color rather than becoming a viewer.
Document that a *proper* disconnect policy (a 20-second countdown and
auto-resign) is a later step; this step only stops seats leaking.

When a message arrives, look up that connection's color and pass it through:
`session.submit(message, color)`.

Mark socket-level code `# pragma: no cover` as elsewhere in the file.

---

## 3. Shell login — username before the window opens

Slide 3: *"Login with username (just for presentation) — do it in a shell, not
via GUI."*

In `client.py`, before the OpenCV window opens, prompt on the terminal:

```
Username:
```

Read it with `input()`. Send it to the server as part of the connection so the
server can log which username took which color. Empty input should re-prompt
rather than being accepted.

Add a protocol message for it in `common/protocol.py` — follow the existing
house style exactly: a type constant, an entry in `_REQUIRED_FIELDS`, a builder
with a docstring documenting the wire contract, and round-trip tests. Do **not**
build the dict by hand anywhere; `protocol.py` remains the single source of
truth for the wire format.

The server should log `<username> joined as w` (or `b` / `viewer`). No password,
no database, no persistence — slide 3 says "just for presentation"; the account
system is slide 4 and a later step. Say that in a comment so the omission reads
as a decision rather than an oversight.

---

## Verify

1. `.\check.ps1 -Full` — 350 + new tests, 100%, pylint 10/10, fuzz clean.
2. `python app.py` still plays exactly as before, both sides, no login.
3. `docker compose up -d`, then two clients:
   - each prompts for a username in its terminal
   - the first says it is white, the second says it is black
   - **white cannot move black's pieces and vice versa**
   - a third client is a viewer and can move nothing, but sees the board update
4. Close the white client and reconnect it — it gets white back, not viewer.

## STOP after Step 4

Commit as `feat: assign colors on connect and enforce ownership server-side (Step 4)`
and stop. Do not start passwords, ELO, matchmaking, rooms or logging.
