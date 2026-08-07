# Kung-Fu Chess

Real-time chess: both players move at once, no turns. Every move takes travel
time and every piece has a cooldown before it can act again, so two pieces can
genuinely be mid-move at the same instant. There is no checkmate — capturing
the opposing king ends the game immediately.

Repo: https://github.com/nirel5-create/kungfu-chess
Architecture report (live): https://nirel5-create.github.io/kungfu-chess/ARCHITECTURE_REPORT.html

## Run

Three ways to play, all verified against this checkout.

### 1. Offline, one process, one keyboard

```bash
python app.py
```

Both colours on one board, one person moving both sides. No login, no
network. This is the engine and renderer with nothing else attached.

### 2. Server and client, no Docker

```bash
python server.py     # terminal 1 -- listens on ws://0.0.0.0:8765
python -m client      # terminal 2 -- one per player/viewer
```

`server.py` works with no database at all: if `DATABASE_URL` is not set, it
logs that Postgres is unreachable and serves games anyway (accounts/ratings
are not implemented yet either — see "What's implemented" below). Run
`python -m client` again in another terminal for a second player, a third
for a viewer, and so on.

### 3. Server and client, with Docker

```bash
docker compose up -d --build   # starts the server + Postgres containers
python -m client                # on the host, one per player/viewer
```

The client always runs on the host (it opens a real window and needs a
display and audio device, which the container does not have); only the
server and its database run in Docker. `docker compose down` stops both
containers; `logs/server.log` is bind-mounted to the host (see below) and
survives it.

## What a player sees

1. **Username**, typed at a terminal prompt (`python -m client` asks before
   anything else opens) — free text, no password, no account.
2. A small **Room** dialog (a real OS window, not drawn inside the game):
   a text box and three buttons.
   - **Create** — makes a new room named whatever was typed; the server
     refuses if that name is already taken.
   - **Join** — enters an existing room by that exact name; refused if no
     room by that name exists.
   - **Play** — skips rooms entirely and joins the ordinary shared game
     (this is the slide's "Cancel" button, renamed: it does not abort
     anything, it finds a game).
   - A room's id is drawn at the top of the window for as long as you are
     in one.
3. **Colour**, assigned by the server: the first person into a game is
   white, the second is black, everyone after that is a viewer who can
   watch but not move.
4. The board itself, with **sound** (move/capture/promotion/jump/game-over)
   and an on-screen mute indicator — press **m** to toggle it. **Esc**,
   **q**, or the window's own close button all quit cleanly.

## Where things live

The one rule that explains the layout: **every layer knows only what is
below it.** The dependency arrow never points up.

```
server.py     the network process -- every live game, every connection, who is seated where
client.py     app.py's frame loop with a websocket instead of a local engine
  |
  +--> common/     the wire format, game/seat lifecycle, ownership checks, the
  |                pub/sub bus, the Postgres connection, shared file logging
  |
  +--> client/     sound, deriving score/log/sound/banner events from snapshots,
  |                the tkinter room dialog
  |
  +--> view/       turns a GameSnapshot into pixels; never touches game state
  |
  +--> input/      pixel clicks -> cells -> engine calls; decides nothing about chess
  |
  +--> engine/     GameEngine: application guards, then delegates. Owns the
         |         game-over flag and nothing else.
         |
         +--> rules/     MoveValidator: geometry. Stateless. Answers yes/no.
         |
         +--> realtime/  RealTimeArbiter: the clock, active motions, arrival
         |               order, captures; a piece in flight or airborne.
         |
         +--> model/     Board (who sits where, storage only) and Config
                         (every rule of the game, as data).
```

`main -> engine -> {realtime, rules} -> model`, plus `main -> input`, and
`server.py/client.py -> common -> engine` (via `common/net.py`),
`client.py -> {client, view, input, common}`. No cycles. `input` imports
nothing from the rest: the controller is handed its engine.

## Checks

```powershell
.\check.ps1          # fast: full test suite + pylint (~1 min) -- run between steps
.\check.ps1 -Full     # adds 100% coverage + a 2000-game fuzz run (~5-6 min) -- run before pushing
```

- **tests** — `python -m pytest -q`, currently 446 tests (74 of them subtests).
  While iterating, `python -m pytest -q -m "not slow"` runs the 444 that are
  not the property-based fuzz test, in well under 5 seconds.
- **pylint** — `python -m pylint common server.py client.py client`, must
  score 10.00/10. `engine/`, `model/`, `rules/`, `realtime/`, `boardio/`,
  `texttests/`, `view/`, `input/` are mentor-authored/frozen and out of
  scope for this gate.
- **coverage** (`-Full` only) — 100% required on `model`, `rules`,
  `realtime`, `engine`, `input`, `boardio`, `texttests`, `view`, `common`,
  `main`, and the `client` package. `app.py`, `view/img.py` and
  `tools/simulate.py` are excluded (they need a real display); `server.py`
  and `client.py` themselves are socket/GUI-driving code and are not
  covered by this gate either — see their own `# pragma: no cover`
  annotations for what that leaves untested and why.
- **fuzz** (`-Full` only) — `tools\fuzz_game.py 2000`: two thousand random
  games, asserting after every step that piece count never rises, every
  active motion's source cell still holds the mover's own piece, every
  token on the board is one `Config` recognises, a finished game's board
  never changes again, and `wait(a); wait(b)` equals `wait(a + b)`. Real
  bugs were found this way; see `docs/IMPLEMENTATION_NOTES.md`.

## What's implemented

| Slide | Requirement | Status |
|---|---|---|
| 1 | Pub/sub bus driving score, move log, sound, start/end animation | Done |
| 3 | Shell username login, first joiner white / second black, ownership enforced server-side | Done |
| 4 | Persistent accounts | Not done |
| 5 | Play: ELO-based matchmaking | Not done — the Play button joins the one ordinary shared game; no skill matching |
| 6 | Room: Create/Join dialog, room id is the room name, 1st=white/2nd=black/rest=viewer | Done |
| — | Passwords | Not done — login is a free-text username, presentation only |
| — | ELO rating computation/persistence | Not done — Postgres `players` table has a `rating` column, never written to |
| — | Disconnect countdown (a timed reconnection window, then forfeit) | Not done — a disconnect holds the seat forever; reconnecting under the same username gets it back with no time limit |
| — | Multiple concurrent games, each with its own lifecycle | Done |
| — | Server + client activity logged to file | Done — `logs/server.log`, one `logs/client_<username>.log` per client |
| — | Containerised server + Postgres | Done — `docker compose up -d --build` |

## Documents

| File | What it is |
|---|---|
| `Server_Design.md` | The scaling design doc: how this two-player server becomes a multi-process system, failure modes, and the build order the `docs/internal/STEP*.md` files follow |
| `docs/internal/STEP_A_DOCKER.md` … `STEP7_ROOMS.md` | One file per implementation step (Docker+Postgres, colours+login, game registry, the pub/sub bus, rooms), each with its own IRON RULES and what it deliberately left undone |
| `docs/internal/SERVER_PLAN.md` | The server-phase implementation spec these steps follow |
| `docs/ARCHITECTURE_VISUAL.html` | How the (local) architecture works, with a game simulation running inside it |
| `ARCHITECTURE_REPORT.html` | The full architecture report + quiz |
| `docs/IMPLEMENTATION_PLAN.html` | The plan, decisions first |
| `docs/IMPLEMENTATION_NOTES.md` | Deviations from the design guide, bugs found, SOLID audit, open questions |
| `docs/COMPLIANCE.html` | Every guide section and email requirement, its status, and the test that proves it |

## Where to go when something is wrong

| Symptom | Class |
|---|---|
| A click lands on the wrong square | `BoardMapper` |
| The wrong piece got selected | `Controller` |
| A move is allowed that should not be (or vice versa) | `MoveValidator` |
| A piece arrives at the wrong time, or a capture resolves wrong | `RealTimeArbiter` |
| The game ends when it should not | `GameEngine` |
| A piece is stored or printed wrong | `Board` |
| A *rule* is wrong (how a piece moves, speed, who is the king) | `Config` — data, not code |
| A room/seat/game-lifecycle decision is wrong | `common/registry.py` |
| A move reached the engine for the wrong colour, or was silently dropped | `common/net.py`'s `GameSession.submit` |

## Changing the rules

There is no `if piece == "R"` anywhere in the engine. A piece's movement is a list of
`Ray`, and that is all the engine ever reads.

```python
from model.config import Config, Ray, TARGET_EMPTY, TARGET_ENEMY

# a brand-new piece: glides up to three diagonally, but only captures straight
movement["D"] = ([Ray(dr, dc, max_steps=3, target=TARGET_EMPTY) for dr, dc in DIAGONAL]
               + [Ray(dr, dc, max_steps=1, target=TARGET_ENEMY) for dr, dc in ORTHOGONAL])

# change an existing piece: this rook only goes two
movement["R"] = [Ray(dr, dc, max_steps=2) for dr, dc in ORTHOGONAL]

# a pawn that reaches the end walks back instead of promoting
movement["wP2"] = [Ray(1, 0, max_steps=1, target=TARGET_EMPTY)]
config = Config(movement=movement, promotions={"wP": "wP2"})
```

Source edits required: none. `tests/unit/test_custom_game.py::TestCustomGameIsDataOnly`
fails the day that stops being true.

### The `Ray` fields

| Field | Meaning |
|---|---|
| `dr, dc` | direction, in cells per step |
| `max_steps` | how far; `None` = slide until blocked or off-board |
| `can_jump` | ignore whatever is in between (the knight) |
| `target` | what may sit on the destination: `TARGET_ANY` / `TARGET_EMPTY` / `TARGET_ENEMY` |
| `gated` | ray only applies from the mover's own start row (the pawn's double step) |

## Tests

```
tests/
  helpers.py            shared fixtures. No patching: fakes are handed in through constructors.
  unit/                 one file per unit, named after what it tests
  integration/
    scripts/*.kfc       text scripts with their expected board written inline
    test_text_scripts.py  runs each one through the public command path
  property/             randomised invariant fuzzing (marked slow)
```
