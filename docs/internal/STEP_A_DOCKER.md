# Step A — the existing server + Postgres in Docker Compose

This is Step א from `Server_Design.md` section 10. The goal is deliberately
small: prove that two containers come up and talk to each other. Nothing is
split, nothing is rewritten.

**Explicitly NOT in this step:** splitting the gateway, Redis, NATS, Kubernetes,
Matchmaker or Game Allocator as separate services. Those are steps ב–ה.

---

## IRON RULES (unchanged, plus two)

1. **Never modify an existing test.** All 339 must still pass.
2. **Never edit** `engine/`, `model/`, `rules/`, `realtime/`, `boardio/`,
   `texttests/`, `view/`, `input/`, `app.py`, `main.py`.
3. **Code and comments in English**, house docstring style (say what the module
   owns and what it does NOT own).
4. **New files use CRLF with a final newline.**
5. `.\check.ps1 -Full` must be green before committing.
6. **`app.py` must keep working unchanged** — the offline local game is not
   affected by any of this.
7. **`client.py` keeps running on the host**, not in a container. It needs the
   OpenCV window and the user's display.

---

## What Step A delivers

```
  HOST (Nirel's machine)              DOCKER COMPOSE
 ┌──────────────────────┐          ┌───────────────────────────┐
 │ client.py            │   WS     │  server   (our image)     │
 │ (OpenCV window)      │ ───────► │  port 8765 published      │
 └──────────────────────┘          │         │                 │
                                    │         │ SQL (5432)     │
                                    │         ▼                 │
                                    │  db  (postgres:16)        │
                                    │  named volume for data    │
                                    └───────────────────────────┘
```

Success = all four of these are true:

1. `docker compose up` brings up both containers and neither exits.
2. The server logs that it connected to Postgres and that the schema exists.
3. `client.py` on the host connects to `ws://localhost:8765` and the game is
   playable exactly as before.
4. `docker compose down` then `up` again — the database still has its data
   (proves the volume works), and the game starts fresh.

---

## New files

```
Dockerfile
docker-compose.yml
.dockerignore
requirements.txt
common/db.py                  # the only new Python module
tests/unit/test_db.py
```

Do NOT create a Dockerfile for the client.

---

### `requirements.txt`

Pin the versions actually installed on the host so the container matches. Check
them first with `pip show` rather than guessing:

```
websockets==<installed>
opencv-python==<installed>
numpy==<installed>
psycopg[binary]==<latest 3.x>
```

`psycopg` version 3 is the current PostgreSQL driver for Python. The
`[binary]` extra ships a precompiled build so the image does not need a C
toolchain.

Note in a comment that OpenCV is in the list because the engine packages import
it transitively; if the server image turns out not to need it, moving it to a
separate client requirements file is a later cleanup, not part of this step.

---

### `Dockerfile`

- Base on `python:3.10-slim` — match the host's Python 3.10 so behaviour is
  identical.
- Copy `requirements.txt` first and `pip install`, THEN copy the source. This
  is the standard layer-caching order: dependencies rarely change, so Docker
  reuses that layer and rebuilds are fast. Say so in a comment.
- Copy only what the server needs: `server.py`, `common/`, `engine/`, `model/`,
  `rules/`, `realtime/`, `boardio/`, `input/`. Not `tests/`, not `assets/`,
  not `client.py`, not `app.py`.
- `EXPOSE 8765`, and `CMD ["python", "server.py"]`.
- Add a `HEALTHCHECK` that verifies the port is accepting connections. This is
  the `/health` idea from the mentor's diagram in its simplest form — it is what
  lets an orchestrator know the container is actually alive rather than merely
  running.

### `.dockerignore`

Exclude `.git`, `__pycache__`, `.pytest_cache`, `tests`, `assets`, `docs`,
`*.md`, `htmlcov`, `.coverage`. Explain in a comment that this keeps the image
small and, more importantly, keeps rebuild times short by not invalidating the
build context on unrelated file changes.

---

### `docker-compose.yml`

Two services.

**`db`:**
- image `postgres:16`
- environment: `POSTGRES_DB=kungfu`, `POSTGRES_USER=kungfu`, and a password.
  Read the password from an env var with a development default
  (`POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-devpassword}`) and add a comment
  that a real deployment injects a secret instead — hardcoding a production
  password in a committed file is the mistake this avoids.
- a **named volume** mounted at `/var/lib/postgresql/data`, so data survives
  `docker compose down`.
- a `healthcheck` using `pg_isready`.

**`server`:**
- built from the Dockerfile.
- `ports: ["8765:8765"]` so `client.py` on the host can reach it.
- `depends_on: db: condition: service_healthy` — **this matters**: Postgres
  takes a few seconds to initialise, and without the condition the server
  starts first and fails to connect. Explain that in a comment.
- environment: `DATABASE_URL` pointing at `db` by service name
  (`postgresql://kungfu:...@db:5432/kungfu`). Note in a comment that `db` is a
  hostname Compose resolves on its internal network — this is exactly the
  "no service knows another's address" idea from the design doc, at the
  smallest possible scale.
- `restart: unless-stopped`.

---

### `common/db.py` — the only new logic

Small and honest. This step does not implement accounts or ELO (that is a later
step); it proves the connection works and puts the schema in place.

**What db.py owns:** opening a connection from `DATABASE_URL`, creating the
schema if absent, and reading/writing a player's rating.
**What it does NOT own:** password hashing, ELO arithmetic, sessions, or any
game logic.

Required API:

```python
DEFAULT_RATING = 1200

def connect(url=None): ...          # url defaults to os.environ["DATABASE_URL"]
def ensure_schema(conn): ...        # CREATE TABLE IF NOT EXISTS players (...)
def get_rating(conn, username): ... # -> int, or None if no such player
def upsert_player(conn, username, rating=DEFAULT_RATING): ...  # -> int (stored rating)
```

Schema: `players(username TEXT PRIMARY KEY, rating INTEGER NOT NULL DEFAULT 1200)`.

Two things to do properly, both of which the design doc argues for:

- **Use parameterised SQL** (`%s` placeholders), never string formatting. Note
  in a comment that this is what prevents SQL injection.
- **`upsert_player` must be a single atomic statement** —
  `INSERT ... ON CONFLICT (username) DO UPDATE ...` — not a SELECT followed by
  an INSERT. Comment that this is exactly the read-modify-write race the design
  doc identifies: two containers doing SELECT-then-INSERT can both decide the
  row is missing. One statement lets Postgres serialise it.

`server.py` may be edited (it is ours, not frozen): on startup, connect, call
`ensure_schema`, and log success or failure clearly. **If the database is
unreachable the server must log it and keep serving games** — the design doc
says live games do not depend on the DB, so this is where that claim gets
honoured rather than merely asserted. Wrap the DB startup in try/except and mark
the socket-level code `# pragma: no cover` as elsewhere.

### `tests/unit/test_db.py`

There is no database in the test environment, so **do not** write tests that
need a live server. Test what is pure:

- `connect` raises a clear error when `DATABASE_URL` is absent (no silent None)
- the SQL statements are parameterised — assert the query strings contain `%s`
  and do not contain an f-string-interpolated username
- `upsert_player` issues exactly one statement, using `ON CONFLICT`
- `get_rating` returns `None` for an unknown player and an int for a known one
- `DEFAULT_RATING == 1200`

Use a fake connection/cursor object (record the SQL and params) rather than
mocking a library. If a behaviour genuinely cannot be tested without a real
database, say so and mark that function `# pragma: no cover` — do not fake a
passing test.

---

## Verify, in this order

1. `docker compose build`
2. `docker compose up` — watch both containers; the server must log a successful
   DB connection AFTER Postgres reports healthy.
3. From the host: `python -m client` — the game must be playable as before.
4. `docker compose down` then `docker compose up` again — data survives.
5. `.\check.ps1 -Full` — 339 + the new tests, all green.
6. Confirm `python app.py` still works unchanged.

Report the output of steps 2 and 5. If Docker on Windows needs a path or
line-ending adjustment, say what and why rather than working around it silently.

## STOP after Step A

Commit as `feat: containerise server with Postgres via Docker Compose (Step A)`
and stop. Do not start Redis, NATS, or splitting the gateway.
