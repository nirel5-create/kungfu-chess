# Kung-Fu Chess

Real-time chess: pieces move concurrently, moves take travel time, and capturing a
king ends the game.

Repo: https://github.com/nirel5-create/kungfu-chess
Architecture report (live): https://nirel5-create.github.io/kungfu-chess/ARCHITECTURE_REPORT.html

## Run

```bash
python -m pytest -q -m "not slow"        # 191 tests, ~0.2s -- use this while editing
python -m pytest -q                      # 193 tests, adds the fuzzer (~97% of the runtime)
.\check.ps1                              # the gate: tests + 100% coverage + fuzz
python -m pytest --cov=model --cov=rules --cov=realtime --cov=engine --cov=input --cov=main
PYTHONPATH=. python tools/fuzz_game.py   # thousands of random games, invariant-checked
PYTHONPATH=. python tools/simulate.py    # one scripted game, as renderer-shaped frames

python main.py < some_script.txt         # the text protocol
```

## Where things live

The one rule that explains the layout: **every layer knows only what is below it.**
The dependency arrow never points up.

```
main            entry point + composition root: reads text, wires the objects, prints
  |
  +--> input/       board_mapper.py   pixels -> cells. The only place that knows cell_size.
  |                 controller.py     selection + clicks. Decides nothing about chess.
  |
  +--> engine/      game.py           GameEngine: application guards, then delegates.
         |                            Owns the game-over flag and nothing else.
         |
         +--> rules/    rules.py      MoveValidator: geometry. Stateless. Answers yes/no.
         |
         +--> realtime/ arbiter.py    RealTimeArbiter: the clock, active motions,
         |                            arrival order, captures.
         |
         +--> model/    board.py      Who sits where. Storage only.
                        config.py     Every rule of the game, as data.
                        motion.py     A piece in flight.
                        jump.py       A piece airborne.
```

`main -> engine -> {realtime, rules} -> model`, plus `main -> input`. No cycles.
`input` imports nothing from the rest: the controller is handed its engine.

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

Source edits required: none. `tests/test_main.py::TestCustomGameIsDataOnly` fails the
day that stops being true.

### The `Ray` fields

| Field | Meaning |
|---|---|
| `dr, dc` | direction, in cells per step |
| `max_steps` | how far; `None` = slide until blocked or off-board |
| `can_jump` | ignore whatever is in between (the knight) |
| `target` | what may sit on the destination: `TARGET_ANY` / `TARGET_EMPTY` / `TARGET_ENEMY` |
| `gated` | ray only applies from the mover's own start row (the pawn's double step) |

## How correctness is checked

Unit tests cover the cases we thought of. The fuzzer covers the ones we did not: it
plays thousands of random games and, after **every step**, asserts five things that must
always hold.

1. Piece count never rises.
2. Every active motion's source cell still holds a piece of the mover's colour.
3. Every token on the board is one `Config` recognises.
4. Once the game is over, the board never changes again.
5. `wait(a); wait(b)` is identical to `wait(a + b)`.

Three real bugs were found this way. They are written up in 
  `docs/IMPLEMENTATION_NOTES.md`
none of them could be expressed as a `print board` assertion.

## Documents
| File | What it is |
|---|---|
| `docs/ARCHITECTURE_VISUAL.html` | How the architecture works, with a game simulation running inside it |
| `ARCHITECTURE_REPORT.html` | The full architecture report + quiz |
| `docs/IMPLEMENTATION_PLAN.html` | The plan, decisions first |
| `docs/IMPLEMENTATION_NOTES.md` | Deviations from the design guide, bugs found, SOLID audit, open questions |
| `docs/COMPLIANCE.html` | Every guide section and email requirement, its status, and the test that proves it |

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
