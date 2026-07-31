# Step 8 — passwords and ELO (slide 4)

Slide 4: *"At Home screen: Login with username + password (save at SQLite db on
server side) — do it in a shell, not via GUI. Add rating (starting from 1200,
moving up and down by ELO)."*

Two halves, and the second is why the first matters: a rating only means
anything if a username belongs to one person.

> **On SQLite:** the slide says SQLite, but `Server_Design.md` argues at length
> why this project uses PostgreSQL instead — global file lock, no coordinating
> process, and read-modify-write races on exactly this rating update. Postgres
> is already running in `docker-compose.yml`. Keep it, and note the deviation
> in the README's status table so it reads as a documented decision rather than
> a miss.

---

## What already exists (verified — do not rebuild)

- `common/db.py`: `DEFAULT_RATING = 1200`, `ensure_schema`, `get_rating`,
  `upsert_player`, and an injectable `connector` for testing.
- The `players` table already has a `rating` column, defaulted to 1200.
- `GameRegistry` already publishes `GAME_END` with
  `{"game_id", "winner", "seats"}` — **`seats` is `{username: color}`**, which
  is exactly what a rating update needs. `server.py` already subscribes to it
  to log the winner.

**So ELO attaches as one more subscriber. If you find yourself editing
`GameRegistry`, stop** — the module docstring says in as many words that this
is what the bus was for.

---

## IRON RULES

1. **Never modify an existing test.** All 446 must still pass.
2. **Never edit** `engine/`, `model/`, `rules/`, `realtime/`, `boardio/`,
   `texttests/`, `view/`, `input/`, `main.py`.
3. **`app.py` must keep working exactly as it does now** — offline play has no
   login at all.
4. **Code and comments in English**, American spelling.
5. **CRLF with a final newline** on every new/edited file.
6. `.\check.ps1` (fast) must pass before you run `-Full`.
7. **Do not** implement the disconnect countdown or ELO-based matchmaking.

---

## 1. `common/elo.py` — the arithmetic, pure

No database, no I/O, no logging. This is the one piece that is entirely
testable, so it is the one that gets thorough tests.

```python
K_FACTOR = 32

def expected_score(rating, opponent_rating): ...   # -> float in (0, 1)
def new_ratings(white, black, winner, k=K_FACTOR): ...  # -> (new_white, new_black)
```

- `winner` is `"w"`, `"b"`, or `None` for a game with no result.
- **`None` must return the ratings unchanged.** A game with no winner — an
  infrastructure failure, a game abandoned by both players — must not cost
  anyone rating. `Server_Design.md` already argues this ("a game that is not
  counted", not a draw); implement it that way.
- Ratings are integers. Round once, at the end, and make sure the two changes
  are **equal and opposite** so total rating is conserved — rounding each side
  independently can leak or create rating points. Say so in a comment.

### Tests — `tests/unit/test_elo.py`
1. two equal ratings give an expected score of exactly 0.5 each
2. a much higher rating gives an expected score close to 1
3. `expected_score(a, b) + expected_score(b, a) == 1` for several pairs
4. the winner gains and the loser loses
5. the gain and the loss are equal in size (total rating conserved)
6. beating a much stronger opponent gains more than beating an equal one
7. beating a much weaker opponent gains little
8. `winner=None` returns both ratings unchanged
9. results are integers, not floats
10. a custom `k` scales the change

---

## 2. `common/db.py` — passwords and rating writes

### Schema

Add `pw_hash` and `salt` columns to `players`.

**A trap to handle explicitly:** `ensure_schema` uses
`CREATE TABLE IF NOT EXISTS`, so an **existing** table will not gain new
columns — the volume from earlier testing already holds a `players` table
without them. Add idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
statements so an existing database is upgraded rather than silently left
broken. Say in a comment that this was checked, not assumed.

### Password handling

```python
def create_player(conn, username, password): ...   # -> True, or False if taken
def verify_password(conn, username, password): ... # -> bool
def update_ratings(conn, white_user, black_user, white_rating, black_rating): ...
```

- **Never store a plaintext password.** Use `hashlib.pbkdf2_hmac` with a random
  per-user salt from `secrets.token_bytes` and a realistic iteration count.
  `hashlib` and `secrets` are both standard library — no new dependency.
- **Comparison must be constant-time** (`hmac.compare_digest`), not `==`.
- First login for a username creates the account (slide 4: *"first time,
  whatever password he writes, that is the password"*); later logins must match.
- Parameterised SQL only, as the existing code already does.
- `update_ratings` writes both players in **one statement or one transaction** —
  not two separate writes, which could leave one applied and one not.

### Tests — `tests/unit/test_db.py` (add, never modify existing)
Use the injected connector and a fake cursor, as the file already does. **No
monkeypatching** — the mentor forbids it and this file is already clean.
1. `create_player` stores a hash, and the plaintext appears nowhere in the SQL
   or parameters
2. two users with the same password get **different** stored hashes (the salt
   works)
3. `verify_password` accepts the right password and rejects a wrong one
4. `verify_password` returns False for an unknown username, without raising
5. `update_ratings` issues one statement, parameterised

---

## 3. Server — verify at login, update on game end

**At login:** the client now sends a password with the username. If the account
exists, verify it; if not, create it. On failure reply
`protocol.error("bad_password")` and close, exactly as `already_connected` does.

If the database is unreachable, **log it and let the player in anyway.**
`Server_Design.md` promises that live games do not depend on Postgres, and this
is where that promise is either kept or broken. Say so in a comment.

**At game end:** a `GAME_END` subscriber reads `seats` and `winner`, looks up
both ratings, computes new ones with `common/elo.py`, and writes them back. It
must:
- do nothing when `winner` is `None`
- do nothing when either seat is missing (a game that never had two players)
- ignore viewers — only the `"w"` and `"b"` seats
- **never raise into the registry.** Wrap it; a database failure must not stop
  the tick loop. Log the failure and move on — that is the `write-behind`
  behaviour the design doc describes.

Log the rating change for both players.

### Tests — `tests/unit/test_ratings.py`
Test the subscriber as a pure function with a fake connection:
1. a normal win updates both ratings correctly
2. `winner=None` writes nothing
3. a game with only one seated player writes nothing
4. viewers are ignored
5. a database error is swallowed, not raised

---

## 4. Client — prompt for a password

After the username prompt, prompt for a password on the terminal. Use
`getpass.getpass` so it is not echoed — standard library, and typing a password
in plain view is exactly the kind of detail a reviewer notices.

Send it with the login message. **Extend `protocol.login` to carry it**, with a
docstring saying the password is sent as typed over a local WebSocket and that a
real deployment would require TLS — an honest limitation stated is better than
one left for a reader to find.

On `bad_password`, print the reason and exit before the window opens, exactly as
the existing refusal path does.

---

## Verify by eye

1. `.\check.ps1` fast, then `-Full`.
2. `python app.py` unchanged — no login at all.
3. `docker compose down && docker compose up -d --build` (the schema changed).
4. New username + any password → gets in, rating 1200.
5. Same username, **wrong** password → refused on the terminal, no window.
6. Same username, right password → gets in.
7. Two players play to king capture → both ratings change in `logs/server.log`,
   winner up and loser down by the same amount.
8. Reconnect and confirm the new rating persisted.
9. Stop only the `db` container and confirm a game still starts and plays.

## STOP after Step 8

Commit as `feat: passwords and ELO ratings (slide 4)` and stop. Do not start the
disconnect countdown or matchmaking.
