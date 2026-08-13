# Kung-Fu Chess

Real-time chess: both players move at once — no turns — every move has travel time and a cooldown, and capturing the king ends the game.

Repo: https://github.com/nirel5-create/kungfu-chess

![Gameplay demo](docs/demo.gif)
<!-- TODO: record a short clip of a real two-player game and save it here as docs/demo.gif -->

## Quick start

Four ways to play. All four are verified against this checkout.

### 1. Offline, one process, one keyboard

```bash
python app.py
```

Both colours on one board, one person moving both sides — no login, no network. Verified: starts and runs with no errors.

### 2. Server and client, no Docker

```bash
python server.py     # terminal 1 -- listens on ws://0.0.0.0:8765
python -m client      # terminal 2 -- one per player/viewer
```

No database is required to start: with `DATABASE_URL` unset, `server.py` logs that Postgres is unreachable and serves games anyway (accounts still work for the session, but ratings don't persist across a restart). Run `python -m client` again in another terminal for a second player, a third for a viewer, and so on.

Verified: started the server standalone and opened a websocket connection to `ws://localhost:8765` — it accepted it.

### 3. Server and client, with Docker

```bash
docker compose up -d --build   # starts the server + Postgres containers
python -m client                # on the host, one per player/viewer
```

The client always runs on the host — it opens a real window and needs a display and audio device the container doesn't have. `docker compose down` stops both containers; `logs/server.log` is bind-mounted to the host and survives it.

Verified: built and started both containers, confirmed in the logs that the server connected to Postgres and was listening, connected a client, then tore the stack down cleanly.

### 4. Two people, two machines

The client reads its server address from `KUNGFU_SERVER`, falling back to
`ws://localhost:8765` when it is unset — so nothing above changes if you run
everything locally.

**On the same network**, one machine runs the server and the other points at it:

```bash
python server.py                                          # machine A
KUNGFU_SERVER=ws://192.168.1.42:8765 python -m client     # machine B
```

Use machine A's local IP address, not `localhost`. On Windows, PowerShell sets
the variable differently:

```powershell
$env:KUNGFU_SERVER="ws://192.168.1.42:8765"
python -m client
```

**Across the internet**, the server needs to be somewhere both players can
reach. The `Dockerfile` and `docker-compose.yml` deploy as-is to any container
host; on Railway it is a GitHub import plus a Postgres service, with
`DATABASE_URL` pointed at it. Players then need only the client:

```powershell
$env:KUNGFU_SERVER="wss://your-app.up.railway.app"
python -m client
```

Note `wss://` rather than `ws://` — a hosted server is served over TLS — and no
port, since the host routes it.

Verified: deployed to Railway with a Postgres service, connected a client from
a different machine over `wss://`, created a room, and confirmed the server
logged the connection.

**If the client fails with `CERTIFICATE_VERIFY_FAILED`**, the local certificate
store is out of date — this is a machine problem, not a project one:

```powershell
pip install --upgrade certifi
$env:SSL_CERT_FILE=(python -c "import certifi; print(certifi.where())")
```

## What a player sees

1. **Username and password**, typed at a terminal prompt (`python -m client` asks before any window opens) — the password is never echoed. A new username creates an account on the spot; an existing one must match its stored password, or the login is refused and re-prompted.
2. The **Home** dialog (a real OS window, not drawn inside the game): shows "Logged in as `<username>` (rating `<rating>`)" and three buttons.
   - **Create** — makes a new room named whatever was typed; refused if that name is already taken.
   - **Join** — enters an existing room by that exact name; refused if no room by that name exists.
   - **Play** — finds an opponent within ±100 rating, showing a live "searching" dialog with a countdown; gives up after 60 seconds with "No opponent found."
3. **Colour**, assigned once seated: the first person into a game is white, the second is black, everyone after that is a viewer who can watch but not move.
4. The board itself, with **sound** (move/capture/promotion/jump/game-over) and an on-screen mute indicator — press **m** to toggle it. **Esc**, **q**, or the window's own close button quit cleanly. A disconnected player gets a 20-second countdown before the game auto-forfeits to whoever is still connected; reconnecting under the same username inside that window returns you to the same seat.

## Project layout

The one rule that explains it: **every layer knows only what is below it.** The dependency arrow never points up.

```
server.py     thin entry point; the real server lives in server/       (run: python server.py)
server/       every live game, every connection, who is seated where
client/       app.py's frame loop with a websocket instead of a local engine (run: python -m client)
  |
  +--> common/     wire format, game/seat lifecycle, ownership checks, the
  |                pub/sub bus, the Postgres connection, shared file logging
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

## Checks

```powershell
.\check.ps1          # fast: full test suite + pylint
.\check.ps1 -Full     # adds 100% coverage + a 2000-game fuzz run
```

| Mode | Enforces | Current result |
|---|---|---|
| `.\check.ps1` | `python -m pytest -q`, then `python -m pylint` on the packages this project owns (`common`, `server.py`, `server`, `client`) | 615 tests passing, pylint 10.00/10 |
| `.\check.ps1 -Full` | Everything above, plus 100% branch coverage on `model`, `rules`, `realtime`, `engine`, `input`, `boardio`, `texttests`, `view`, `common`, `main`, and `client`, plus `tools\fuzz_game.py 2000` | 100% coverage, a clean 2000-game fuzz run |

`engine/`, `model/`, `rules/`, `realtime/`, `boardio/`, `texttests/`, `view/`, `input/` are frozen by choice, not by authorship — they're proven correct by the 2000-game fuzz suite and covered by the coverage gate instead of the pylint one.

## Documents

| File | Answers |
|---|---|
| `ARCHITECTURE_DECISIONS.md` (Hebrew) | Why is the project built this way? Nine decisions that shaped it, and the reasoning behind each. |
| `Server_Design.md` (Hebrew) | How would this scale? Turning the current single-process, two-player server into a design for 100 million registered accounts and 10 million concurrent players. |

## What's not implemented

- **Voluntary resignation.** There is no `resign` message in the protocol. A game only ends by capturing the king, or by the 20-second disconnect grace period running out on a seated player.
- **Horizontal scaling.** The server is one process today. Sharding across processes, a message bus (NATS), Redis, a Game Allocator, geographic regions, and event sourcing at scale are all designed and reasoned about in `Server_Design.md`, but none of it is built.
