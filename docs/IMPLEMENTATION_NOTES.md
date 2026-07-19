# Implementation Notes — Kung-Fu Chess

Living document. Updated as decisions are made and as reality forces changes.

Source of truth, in this order:
1. **Mentor** — highest authority. Overrides the Design Guide where they conflict.
2. Live VPL score (green = correct, no argument).
3. Design Guide (Ultra.Code, "Kung Fu Chess — Design Guide", last modified 9 Jul 2026).
4. Reference gameplay video.

---

## 1. Architecture Impact Note — Concurrent Per-Piece Movement

Written in the shape required by Design Guide §17 ("Before implementing a feature,
students write a short architecture impact note").

**Decision:** Movement is concurrent. The block applies **only to the piece that is
currently moving**. Every other piece, on both sides, is free to move at the same time.
Collisions between moving pieces are resolved in the arbiter.

**Authority:** Mentor. The reference implementation blocks only the moving piece, and
without concurrency the game loses a substantial part of how it actually plays.

**Relation to the Design Guide:** §3.13 and §10 describe a common route with one active
motion, and classify simultaneous movement as an Extra Route feature. **That
classification is overridden.** Concurrency is core behaviour here, not an optional
extra. The guide remains authoritative on layering, ownership, and dependency direction
— none of which this changes.

### Affected layers
| Layer | Change |
|---|---|
| `realtime` (RealTimeArbiter) | Single `_active_motion` becomes a keyed collection of active motions. Arrival resolution becomes ordered and collision-aware. |
| `engine` (GameEngine) | The one-active-motion guard changes from a global query to a per-piece query. |
| `model`, `rules`, `io`, `input`, `view` | **Unchanged.** |

### New state required
- A collection of active `Motion` objects keyed by source cell (the moving piece stays
  logically on its source cell until arrival — Design Guide §10 "Logical Board Update
  Rule" — so the source cell is a stable key for the duration of the motion).
- No new state inside `Board`. Board continues to own logical occupancy only
  (Design Guide §19: "Mistake: Storing active Motion objects inside Board").

### Public API impact
- `RealTimeArbiter.is_moving(cell) -> bool` already exists and becomes **the only**
  motion guard the engine consults.
- `RealTimeArbiter.has_active_motion() -> bool` is retained for API compatibility
  (§20 lists it) but the engine no longer depends on it.
- `RealTimeArbiter.advance_time(ms) -> ArrivalEvents` signature unchanged; it may now
  return more than one arrival.
- No signature changes to `GameEngine.request_move`, `GameEngine.wait`, or
  `RuleEngine.validate_move`.

### Layers that must remain unchanged
`model/` (Board, Position, Piece), `rules/` (PieceRules, RuleEngine), `io/`
(BoardParser, BoardPrinter), `input/` (BoardMapper, Controller), `view/` (Renderer).
Dependency direction stays `main -> engine -> {realtime, rules} -> model`.

### Tests required
- Unit: two pieces move concurrently and both arrive.
- Unit: re-commanding a piece that is already moving is rejected with `motion_in_progress`.
- Unit: commanding a *different* piece while one moves is accepted.
- Unit: both colours move at the same time (the reason the feature exists).
- Regression: existing tests asserting the *global* block are rewritten to the new
  behaviour. This is part of the change, not breakage.
- Unit: arrivals inside one `advance_time` window resolve in chronological order.
- Unit: two enemies arriving at the same cell — later arriver captures the earlier.
- Unit: existing airborne-reversal behaviour still holds with several motions active.
- Regression: the whole existing suite stays green under the common-route policy.

### Policy: per-piece blocking, unconditionally
The global one-active-motion guard is **removed**, not made configurable. The only
guard that remains is `is_moving(source)` — a piece already in motion cannot be
re-commanded. Every other piece, on both sides, is free to move concurrently.

Rationale: the mentor is the highest authority and stated the reference implementation
blocks only the moving piece. Without true concurrency the game loses its core —
two players acting at the same time. Frame-differencing of the reference video
confirms it: ~26% of frames show two separate motion tracks travelling at once.

The Design Guide classifies simultaneous movement as Extra Route feature #1. That
classification is noted but does not change the decision.

---

## 2. Deviations (סטיות)

Every deviation from the Design Guide is recorded here with its reason. Rule: when an
edge case forces a choice, take the conservative option and log it.

### D-0a. Friendly occupant at arrival cancels the motion
- **Trigger:** Only reachable once motions are concurrent — two friendly pieces are
  both legally commanded to the same empty cell, the first lands, the second arrives
  and finds a friend. The validator cannot prevent this; it ran at command time.
- **Old behaviour:** `board.move` clobbered the friendly occupant. Unreachable through
  the engine, so it went unnoticed — one existing test
  (`test_friendly_arrival_at_airborne_cell_not_reversed`) had encoded it by calling
  `start_motion` directly, asserting that a rook eats its own king.
- **Decision:** **Cancel the arrival.** The mover stays on its source cell; the board is
  untouched. This is the conservative option and matches Design Guide Extra Route #4,
  "Cancellation when the destination becomes occupied before arrival".
- **Test changed:** the assertion above was rewritten to the corrected behaviour. Its
  original intent (no reversal for a friendly) is still proven — a reversal would delete
  the arriver, and it does not.

### D-0b. A captured piece's queued motion is dropped at the moment of capture
- **Trigger:** Concurrency only. A piece sets off on a long trip; an enemy lands on its
  source cell before it arrives and takes it there (the mover is still logically on its
  source until arrival — Design Guide §10). The dead piece's motion was still queued.
- **Bug it caused:** at arrival the stale motion ran `board.move(source, destination)`
  and **teleported whoever was standing on that cell** to the dead piece's destination.
- **First attempt (rejected):** compare `board.piece_at(source)` to `motion.piece` at
  resolution time. This compares *tokens*, not identities. Reproduced failing case:
  wR#1 sets off; bR takes it on its source; wR#2 then takes bR and settles on that same
  cell; at wR#1's arrival the check reads `"wR" == "wR"` and passes — teleporting wR#2.
- **Decision:** cancel by **event, not by comparison**. When an arrival captures an
  occupant, drop any motion keyed by that cell (`_active_motions.pop(destination)`).
  A dead piece cannot finish its trip. No token comparison, no reliance on identity.
- **Note:** this removes the need for `Piece(id=...)` *for this bug*. Stable ids remain
  valuable for snapshots and animation (Decision 05), just not load-bearing here.

### D-0c. Simultaneous arrivals: the departure resolves first
- **Trigger:** two motions with the identical `arrival_time`. The mentor's rule ("the
  later arriver captures the earlier") has no answer here — neither is later.
- **Decision:** resolve in `(arrival_time, source)` order. A piece leaving a cell in the
  same millisecond another arrives there leaves first; the arriver takes the vacated
  cell and nobody is captured. Deterministic and covered by a test.

### D-0d. A king capture stops arrivals immediately
- **Trigger:** Concurrency only, and **found by the fuzzer (seed 3)**, not by hand. In
  the one-motion model this was unreachable: the motion that took the king was the only
  one in the air, so the board froze by itself. With concurrency other pieces are still
  flying when the king dies, and they kept landing — the board changed after game over.
- **First attempt (rejected):** make `GameEngine.wait` a no-op once `game_over` is set.
  This only froze the board *between* calls, not *within* one. It produced a real
  violation of a written requirement — §17 Iteration 5: **"Partial wait followed by
  remaining wait equals one full wait."** With that fix, `wait(4000)` and
  `wait(1000); wait(3000)` gave different boards.
- **Decision:** stop inside the arbiter. `_resolve_motions` breaks out of the arrival
  loop the moment `_king_captured` is set, so nothing lands after the game is decided —
  regardless of how the caller slices its waits. `wait` also stays a no-op afterwards.
- **Guide basis:** §14 / Iteration 6 ("After game over, further clicks do not change the
  board"; "Game over prevents further moves") plus §17 Iteration 5 (wait additivity).
  Note the guide only mentions *clicks*; extending this to elapsed time is an
  interpretation, but the wait-additivity rule is explicit and forced the shape of the fix.

### D-7. Rest states: short_rest returns to idle, not long_rest
- **Source conflict.** The sprite `config.json` files say `short_rest ->
  long_rest`. The mentor said in the video, of a jump: *"אחרי קפיצה במקום הולכים
  למנוחה קצרה ופס"* -- short_rest, then done. The mentor also said the jump config
  itself contains a mistake he would fix. Per the project's authority rule
  (mentor > config files), we follow the mentor: `short_rest -> idle`.
- **What was built.** The engine now has a rest state machine:
  `idle -> move -> long_rest -> idle` and `idle -> jump -> short_rest -> idle`.
  A resting piece refuses `request_move` and `request_jump` (reason `resting`) --
  a rule of the game, so it lives in the engine, not the view. The snapshot
  reports `idle / moving / jumping / resting` so the renderer can pick a sprite.
- **Durations are Config data.** `long_rest_ms=2000`, `short_rest_ms=1000` are
  sensible defaults; the real numbers live in the sprite config (frames / fps),
  which is graphics data the engine must not read. A caller injects exact values
  when the view knows them -- a one-line change, no engine edit.
- **Two real bugs the fuzzer caught here:** (1) a rest started from the current
  clock instead of the arrival/jump-end time, breaking `wait(a)+wait(b) ==
  wait(a+b)`; fixed by measuring from the event time. (2) a piece captured while
  resting left its rest behind on the now-empty cell; fixed by clearing rest on
  capture and when the mover leaves its source. A sixth fuzz invariant now
  asserts a resting piece never accepts a move.

### D-6. The io package is named `boardio`, not `io`
- **Guide:** §5 names the package `io/`.
- **Problem:** `io` is a Python standard-library module. A local `io/` package cannot
  be imported from — `from io.board_parser import BoardParser` raises
  `ModuleNotFoundError: 'io' is not a package`, always. Verified, not assumed.
- **Decision:** `boardio/`. Same responsibility, same contents, a name that works.
  The guide is written language-agnostically; this is Python forcing the change.

### D-0. Movement is concurrent, not one-at-a-time
- **Guide:** §3.13 / §10 — common route allows one active motion; simultaneous movement
  is Extra Route feature #1.
- **Decision:** **Overridden by the mentor.** Concurrency is core. Only the moving piece
  is blocked.
- **Status:** Deliberate, authorised.

### D-1. Pawn promotion is implemented (guide says it is not)
- **Guide:** §3.5 "The game does not implement check, checkmate, castling, en passant,
  or promotion." §7 "Pawn has no promotion."
- **Current code:** `Config.promotion_target` / `Config.promotion_row` implement promotion.
- **Decision:** **Keep.** Working behaviour; removing it buys nothing.
- **Status:** Deviation retained deliberately. Revisit only if the mentor says it must go.

### D-2. Pawn initial two-step move is implemented (guide says it is not)
- **Guide:** §7 "Pawn has no initial two-step move."
- **Current code:** `Config.start_row` gates a double-step origin.
- **Decision:** **Keep**, same reasoning as D-1.
- **Status:** Deviation retained deliberately.

### D-3. `jump` command exists and is not in the Design Guide
- **Guide:** The DSL contains exactly four commands: `Board`, `click`, `wait`,
  `print board` (§13). `jump` appears nowhere.
- **Current code:** `Game.jump`, `model/jump.py`, airborne reversal — a full feature
  with six documented rules, exercised by VPL.
- **Decision:** **Keep.** Working, fully tested behaviour, cleanly isolated in
  `realtime`, violating no layer boundary.
- **Status:** Deviation retained deliberately.

### D-4. `PieceRules` is data-driven, not one class per piece type
- **Guide:** §6 pattern vocabulary lists "PieceRules — Strategy per piece type"; §7
  shows `legal_destinations(board, piece) -> set[Position]` per piece class.
- **Current code:** movement is a ray table in `Config`; one generic interpreter reads it.
- **Decision:** **Keep the data**, but expose the guide's interface shape
  (`legal_destinations(board, piece)`) over it. A parameterised strategy is still a
  strategy. This directly serves the stated future requirement of user-defined pieces
  and games (mentor email #2), which per-type hand-written classes would obstruct.
- **Status:** Deviation retained deliberately, with the guide's public shape honoured.

### D-5. `main.py` remains the VPL entry point; `app.py` is separate
- **Guide:** §5 package structure names `app.py`.
- **Reason:** `main.py` is the existing text-protocol entry point. The graphical game
  gets its own entry point rather than overloading it.
- **Status:** Deviation retained deliberately.

---

## 3. Open questions

- **Q1. VPL impact is unknown.** It is not known whether any VPL test commands a
  second piece while a first is in motion and expects rejection. Mitigation: Wave 1 is
  developed on branch `feature/per-piece-motion` and VPL is run immediately after.
  Green -> merge and continue. Red -> stop, report, decide together. `main` stays
  untouched until VPL is known.
- **Q2.** Design Guide §17 orders the extra route *after* the minimal UI works.
  Current plan does it before, per the mentor's instruction.

---

## 5. Change log

| Date | Change |
|---|---|
| (pending) | Wave 0 — baseline captured: 116 tests, 100% coverage. |
| (pending) | Motion model decided: concurrent, per-piece. Mentor overrides guide §3.13. |
| (done) | Fuzzer added: 22,000 random games clean. Found D-0d (board moved after game over). |
| (done) | **Waves A–G shipped.** Closed 15 of the 18 unmet guide sections. `Position`, `Piece`, `GameState`, `GameSnapshot`; `RuleEngine`+`PieceRules` split with `legal_destinations -> set[Position]`; `MoveValidation`/`MoveResult` with stable reasons; `boardio/` (parser+printer); `texttests/` (parser+runner); `Motion`/`Jump` moved to `realtime`; 7 `.kfc` integration scripts with inline expected output. **191 tests, 100% coverage, DAG acyclic.** Only the graphics remain. |
| (done) | **Cycle found and closed.** `Board.render()` imported `BoardPrinter`, making `model -> boardio` — an upward arrow the guide forbids (§5). `render()` removed; the format lives in `BoardPrinter` alone. `model` now imports nothing. |
| (done) | **Wave 3 shipped (SRP + DIP).** `Game` held four responsibilities — pixel mapping, selection, application guards, and a render passthrough — against guide §4 ("GameEngine ... must not own ... rendering, input parsing ... or pixel mapping"). Split into `BoardMapper` (pixels), `Controller` (selection/clicks), `GameEngine` (guards + delegation). `main.py` is now the composition root. `GameEngine` takes optional `validator`/`arbiter` so a fake can be injected — the email forbids monkeypatch and this is what replaces it. **145 tests, 100% coverage.** |
| (done) | **Wave 1 shipped.** `arbiter.py`: `_active_motion` -> `_active_motions` dict keyed by source; arrivals resolved in `(arrival_time, source)` order. `game.py`: guard `has_active_motion()` -> `is_moving(src)`. 2 source files touched; model/rules/io/main untouched. **125 tests, 100% coverage on source.** |
