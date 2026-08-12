# Refactor audit — Stage 1

Working material for docs/internal/REFACTOR_SPEC.md. Deleted in the final commit.

## Scope

**In scope for structural change:** `server.py`, `client/` (the whole package,
matching check.ps1's own pylint scope), `common/` (the whole package). These are
the only packages check.ps1 holds to a 10.00/10 pylint gate, and the only ones
carrying `too-many-*`/`too-complex` suppressions today.

**Frozen (docstring-only, per the spec's own decision):** `engine/`, `model/`,
`rules/`, `realtime/`, `view/`, `input/`, `boardio/`, `texttests/`. None of
these currently has a `too-many-*`/`too-complex` suppression or a >30-line
function, so there is nothing structural to find in them; `boardio/` and
`texttests/` already had their module docstrings brought up to date this
session (see git history) and are left alone here.

**Out of scope entirely: the test suite.** `tests/helpers.py`'s `render()` and
`run_fixture()` are called from 121+ and 20+ sites respectively across ~16
test files (verified this session, before REFACTOR_SPEC.md existed). Any
signature change to either would require editing those test files, which the
non-negotiable rule forbids outright ("No existing test may be modified or
deleted"). No structural finding below touches `tests/`. `app.py` and
`main.py` are not in check.ps1's pylint scope either and are not touched
structurally; both are exercised as entry points in the final report instead.

## Method

Every function/method in the in-scope files was measured by AST (line count
excluding its own docstring, parameter count, nesting depth, boolean-default
parameters) and cross-checked against every existing `# pylint: disable`
naming a `too-many-*`/`too-complex` code. Duplication and error-handling were
checked by direct grep/read.

## Rule 4 — modules over 400 lines

| File | Lines | Fix |
|---|---|---|
| `server.py` | 1276 | Split into `server/` package by responsibility (auth/rooms/matchmaking, the tick loop, the client-connection loop, composition root) |
| `client/__main__.py` | 1161 | Split into `client/` (existing package) submodules: the network link, the frame/draw loop, terminal login, panel/mute drawing, composition root |
| `common/protocol.py` | 446 | Split into `common/protocol/` package: message constructors, snapshot/capture-log encode-decode, dumps/loads/ProtocolError re-exported from `__init__.py` so `protocol.move(...)` etc. keep working unchanged |
| `common/registry.py` | 409 | Extract `_Game`/`AlreadyConnectedError` into `common/registry/game.py`; `GameRegistry` itself stays one class (splitting a single class across files is not "by subject") but the module drops under 400 once those two move out |

Every other in-scope module is already under 200 lines.

## Rule 5 — every existing `too-many-*`/`too-complex` suppression (the master list)

`server.py`:

| Line | Target | Disable | Fix |
|---|---|---|---|
| 121 | module | too-many-lines | resolved by the rule-4 split above |
| 449 | `_run_game_loop` (7 params) | too-many-arguments, too-many-positional-arguments | Stage 3 context object |
| 644 | `_seat_for_choice` (8 params, 7 returns) | too-many-arguments, too-many-positional-arguments, too-many-return-statements | Stage 3 context object + split into the three ways to get a seat + a dispatcher (spec's own finding) |
| 746 | `_handle_client` (9 params) | too-many-arguments, too-many-positional-arguments | Stage 3 context object |
| 880 | `_broadcast_countdown` (6 params) | too-many-arguments, too-many-positional-arguments | Stage 3 context object |
| 908 | `_tick_loop` (7 params, 123 LOC, 7 responsibilities) | too-many-locals, too-many-branches, too-many-statements, too-many-arguments, too-many-positional-arguments | Stage 3 context object + Stage 4 split into one function per responsibility (spec's own finding) |

`client/__main__.py`:

| Line | Target | Disable | Fix |
|---|---|---|---|
| 74 | module | too-many-lines | resolved by the rule-4 split above |
| 140 | `_ServerLink` (many attributes) | too-many-instance-attributes | Stage 3: group the per-round fields (snapshot/color/room/error/countdown pair/result/matchmaking_status/waiting) into one small mutable state object the lock guards, instead of one attribute each |
| 362 | `_receive_loop` (78 LOC, 10-way dispatch) | too-many-statements | Stage 4: dispatch table of `{message_type: handler}` instead of one flat if/elif per type (spec's own finding) |
| 569 | `_draw_mute_indicator` (6 params) | too-many-arguments, too-many-positional-arguments | Stage 3 context object |
| 703 | `build_client` (60 LOC, composition root) | too-many-locals | Stage 4: split the bus-wiring block out of the object-construction block |
| 851 | `_make_on_mouse` (5 params) | too-many-arguments, too-many-positional-arguments | Stage 3 context object |
| 883 | `_play_one_game` (161 LOC, 8 params, nesting 6) | too-many-locals, too-many-statements, too-many-branches, too-many-arguments, too-many-positional-arguments, too-many-nested-blocks | Stage 3 context object + Stage 4 split by responsibility (spec's own finding) |

## Rule 1/2 — other >30-line or >4-param functions the audit found, not already covered by a disable above

| File | Function | Code LOC | Params | Fix |
|---|---|---|---|---|
| `server.py` | `_main` | 59 | 0 | Split composition (registry/matchmaker/bus wiring) from the serve-forever call |
| `client/__main__.py` | `run` | 53 | 0 | Split login from the home/play loop body |
| `client/events.py` | `on_snapshot` | 51 | 2 | Split per-derived-event (move/capture/jump/promotion/game-start) into their own small functions |
| `client/roomdialog.py` | `ask_room` | 51 | 3 | Split widget construction from the `choose()` callback closure |
| `client/overlay.py` | `draw` (BannerOverlay) | — | 5, boolean default | Rule 9: split the boolean-flag branch into two call sites/methods instead of a flag parameter |
| `client/overlay.py` | `_draw_with_backing` | — | 5 | Stage 3 context object |
| `common/db.py` | `update_ratings` | — | 5 | Stage 3: group `(white_user, white_new)`/`(black_user, black_new)` into two pairs instead of 4 loose values |
| `common/protocol.py` | `history` | — | 5 | Stage 3: same white/black pairing |
| `client/__main__.py` | `_prompt_username` | — | boolean default (`mention_quit`) | Rule 9: keep as the one narrow, justified exception (see below) or split into `_prompt_username()`/`_prompt_username_mentioning_quit()` |

`on_mouse` and `_make_on_mouse` were already found this session (see the
`_broadcast_countdown`/`_make_on_mouse` disables above): `on_mouse`'s own
signature is fixed by cv2's callback contract (`event, x, y, flags, param`,
called positionally by the library, not by our code) — `_flags, _param` can
collapse to a single `*_ignored` to bring the declared count to 3, which is
the only change cv2's contract allows; this is not a rule-9 boolean-flag
case, just an external interface.

## Rule 6 — duplication

Confirmed by direct grep: the sequence *log a warning → send `protocol.error`
→ close the socket → return None/None-equivalent* appears **6 times** in
`server.py`, differing only in the log message and the reason string:
`_join_or_refuse` (already-connected-to-game), `_seat_for_choice` twice
(invalid room name, room/join refusal), `_handle_client` three times
(undisplayable username, bad password, already connected). Extract one
`async def _refuse(websocket, log_msg, reason)` helper.

No other 3+-line duplicated block (with only a literal changed) was found in
the in-scope files.

## Rule 10 — error handling

Every existing broad `except Exception` in scope already names a real
boundary with a one-line reason and is left alone, not a violation:
`server.py:257` (password check, DB down), `server.py:309` (rating lookup, DB
down), `server.py:1130` (`_connect_db`, DB down at startup), `server.py:1193`
(`_update_ratings_on_game_end`, DB down), `common/bus.py:68` (one bad
subscriber must not stop the others). No new broad excepts are introduced by
this refactor; no existing one needs a stated reason it does not already have.

## Rule 9 — boolean-flag parameters, full list

`client/overlay.py`'s `BannerOverlay.draw` (or equivalent boolean default)
and `client/__main__.py`'s `_prompt_username(mention_quit=False)` are the only
two boolean-default parameters found in scope. Both are fixed in Stage 4.

## Rules 3/7 — docstrings and comments

Not enumerated function-by-function here on purpose, per the spec's own
ordering ("rewrite docstrings and comments last -- after the splits, most
shrink on their own"): nearly every function in `server.py` and
`client/__main__.py` currently carries a docstring longer than its code,
narrating which Step/slide introduced it, cross-referencing other files'
docstrings, or restating what the code already says — this is the project's
established style throughout its build, not a handful of outliers, so a
per-function pre-listing here would just be stale the moment Stage 2-4 move
or merge the code underneath it. Stage 5 rewrites every docstring touched by
a split (all of them, in practice) for a reader with no project history, per
the spec's "Keep: a genuine design reason... Cut: step numbers, live-testing
fix, cross-references, restatements" rule, and spot-checks the untouched
remainder of each file for the same issues.

## Plan

1. **Split modules** (rule 4): `server/` package, `client/` package split by
   subject inside the existing package, `common/protocol/` package,
   `common/registry/game.py` extraction.
2. **Context objects** (rules 2/5 arg-count half): one per repeated
   collaborator group, named for what it holds.
3. **Split functions by responsibility** (rules 1/5 complexity half, 8, 9):
   `_tick_loop`, `_seat_for_choice`, `_handle_client`(*), `_play_one_game`,
   `_receive_loop`, `build_client`, `_main`, `run`, `on_snapshot`, `ask_room`,
   plus the two boolean-flag parameters.
4. **Remove duplication** (rule 6): the `_refuse` helper.
5. **Docstrings/comments** (rules 3/7): rewritten as each function moves;
   full-file spot-check pass at the end.

(*) `_handle_client`'s own control flow (read login -> loop seat/play) is not
split further than the context-object fix: it is already one linear
responsibility (drive one connection's lifetime), not several, unlike
`_tick_loop`.

## Stage 3 findings (context objects)

Done: `server.state.ServerState` (+ its own nested `_PlayQueue`, split out
because `ServerState` itself tripped too-many-instance-attributes at 8
fields) collapses `_handle_client` 9->2, `_seat_for_choice` 8->4,
`_run_game_loop` 7->3 (via the new `Seat` namedtuple), `_tick_loop` 7->3,
`_play_matchmaking` 5->3, `_seat_matched_pair` 5->3 params.
`client.composition._GameUI` (+ its own nested `_Overlays`, same reason)
collapses `_play_one_game` 8->3.

Two disables the audit expected to clear here do NOT, on inspection --
verified against pylint's actual default max-args (5, not the rule's own
stricter 4), the tool that check.ps1 enforces:

- `client.play._make_on_mouse` (5 params) is called directly by
  `tests/unit/test_main_on_mouse.py`, which constructs two plain dicts
  (`{"rect": ...}`, `{"at_ms": ...}`) and passes them positionally.
  Bundling them into one object would change that call's arity/shape --
  forbidden outright by the non-negotiable rule. Left as-is.
- `client.draw._draw_mute_indicator` (6 params) is not itself tested, but
  was kept matching `_make_on_mouse`'s two-dict shape rather than
  introducing a second, independent representation of the same
  rect/pressed-at state that could drift from it.

`server.tick._broadcast_countdown` (6 params) is untouched here on
purpose: its own params (`game_id`, `game_clients`,
`current_countdown_seconds`, `last_countdown_seconds`, `dead`) are
`_tick_loop`-local per-tick bookkeeping, not ServerState collaborators --
swapping its `registry` param for `state` would not reduce the count.
Deferred to Stage 4, where `_tick_loop` itself is split and this function's
real shape can be designed alongside whatever replaces the loop's own
per-tick locals.

`common.db.update_ratings` and `common.protocol.messages.history` (5
params each) carry no suppression and are not pylint violations under the
default threshold this project's gate actually enforces -- left alone
rather than bundled for a stricter threshold nothing in check.ps1 checks.
