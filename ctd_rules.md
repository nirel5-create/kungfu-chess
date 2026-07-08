# ctd_rules.md: System & Development Guidelines for CTD Project

## 1. Project Overview & Architecture
This document is the absolute source of truth for the **"Kung-Fu Chess" (Concept)** game project developed in Python for the Cracking the Design (CTD) course. The project emphasizes large-scale code management, evaluating design patterns, rigorous automated testing, controlled AI assistance, and scalable cloud system design. The development progresses through three major components: Business Logic, Graphical User Interface (GUI), and Server System Design.

> **Engineering stance:** Because Kung-Fu Chess is a *real-time* game (no turns; every piece runs on its own clock), performance is a first-class design constraint, not an afterthought. All representation and data-structure decisions are governed by the **Engineering Efficiency Doctrine (Section 8)**. Correctness and exact VPL output (Section 2) always outrank speed, but among correct designs, choose the fastest.

## 2. Platform Constraints & I/O (UltraCode)
The system is automatically graded and validated via the UltraCode Virtual Programming Lab (VPL) using standard data streams.
* **Execution Entry Point:** The primary executable file must be named `main.py`.
* **Input Parsing (`stdin`):** The system must read raw text blocks from standard input.
* **Output Formatting (`stdout`):** All system responses and board states must be printed directly to standard output.
* **STRICT VPL RULES:** Do not print prompts, explanations, or debugging text. Exact output match is required by the grading engine.
* **Progression System:** Development is gated by iterations. A test score of 80% or higher is required to unlock the next set of requirements.

## 3. Core Business Logic (Kung-Fu Chess Mechanics)
The base game modifies standard chess rules to operate in real-time.
* **Simultaneous Play:** Both players issue commands and move pieces concurrently without turn-based waiting.
* **Travel Time:** Pieces require a calculated duration to move from the origin to the destination square.
* **Cooldown Period:** Upon arrival, pieces must "rest" for a predefined duration before receiving a new command.
* **Victory Condition:** The game concludes strictly upon the capture of the opponent's King.
* **No Check/Checkmate State:** Kings under threat can escape during the attacker's travel time.

## 4. Current Milestone: Iteration 1 Constraints
* **Objective:** Parse a text board fixture, validate it, infer its dimensions, and print it back in canonical form.
* **Rules:** NO chess rules are implemented in this iteration.
* **Input Format:** Starts with a board keyword, followed by grid representations (e.g., `.` for empty, `W` for White, `B` for Black, `K` for King, `R` for Rook).

## 5. Extensibility & Future Features (System Design)
The architecture must remain flexible to implement the following features seamlessly:
* **Jump In Place:** A vertical jump landing on the current square with a shorter cooldown. Captures attackers if mid-air; gets captured if grounded before the attacker arrives.
* **New Piece Injection:** The system must easily accept new pieces, such as a "Drone" that moves slower and targets a ±2 square bounding box.
* **Animation Engine Support:** Modular visual states for Idle (breathing), Moving (walking/hopping), and Cooldown.
* **Concurrent Logging:** Real-time, dual-column move log (White and Black) timestamped by server arrival times.
* **Dynamic Scoreboard:** Points based on standard values (Pawn=1, Knight/Bishop=3, Rook=5, Queen=9, King=∞), updating upon captures and promotions.
* **Scalable Cloud Networking:** The server logic acts as a matchmaking broker, handling high concurrency without network bottlenecks or execution latency.

## 6. Development Methodology & Version Control
The workflow strictly follows a Spiral Development Model.
* **Micro-Increments:** Code must be written in blocks of 5 to 10 lines at a time.
* **Test-Driven Operations:** Every code increment requires an immediate unit test. Large code blocks without tests are forbidden.
* **Refactoring Phase:** Once tests pass (Red-to-Green), clean and organize the code without altering functional behavior.
* **Git Micro-Commits:** Commits must be made every 10 to 15 minutes of active effort to preserve history.
* **Continuous Committing:** Commit code even if it contains bugs or failing tests. Commits act as experimental checkpoints.
* **Doctrine ≠ premature optimization:** The Efficiency Doctrine (Section 8) governs *how* a feature is built **when its iteration arrives** — it is never a license to build future features early or to inflate a micro-increment. Build the smallest correct thing for the current iteration, but do not choose a representation that a later iteration would be forced to tear out.

## 7. LLM (AI) Usage Policy
* **Contextual Grounding:** AI should ideally be integrated into the IDE to read project files directly.
* **Human Oversight:** AI outputs must be audited to prevent architectural drift or biased, self-fulfilling unit tests.
* **Prompt Logging:** All chat logs and system prompts must be saved for code reviews and methodology analysis.

## 8. Engineering Efficiency Doctrine
This section governs *how* the engine is built at the level of data structures and algorithms — not code style, naming, or comments. It applies from the moment a feature's iteration is unlocked.

**Meta-rule:** Choose the representation for the operation that runs **most often**. Precompute what is static, update state **incrementally**, cache what would otherwise be recomputed, and verify every fast path against a slow, obviously-correct oracle. In a real-time engine the hot path is *move generation, collision, and "is this square attacked?"* — these run continuously, so they set the representation.

* **1. Bitboards over object grids.** Represent the board as integer bit-masks — one per piece type and color — using Python's arbitrary-precision `int`. Bitwise ops (`&`, `|`, `^`, `<<`) run at C speed. Occupancy, attack detection, and legal-move generation become O(1) mask operations instead of scanning a 2-D array every tick. This is the single largest win in a real-time chess engine. *(Same instinct as the bit-manipulation family: masks, XOR, powers of two.)*
* **2. Precomputed attack tables.** Build knight/king jump masks and sliding-piece ray masks **once at startup**, indexed by square (0–63). Move generation is then a table lookup plus a mask — never recomputed per move or per frame. *(Same instinct as a Sieve, Gray-code generation, or precomputing an `isPal` table before backtracking: pay once, read forever.)*
* **3. Cooldowns as an event heap, not a per-frame scan.** Key each piece by its `ready_at` timestamp in a `heapq`; the loop pops only what is due. This is O(log n) per event versus O(n) scanning every piece every tick. *(The scheduling instinct — sort/`bisect` in Job Scheduling — promoted to an event queue.)*
* **4. Incremental state, never rebuild.** On each move, toggle the two affected bits on the relevant bitboards and update an incremental board hash (Zobrist). Do **not** reconstruct the board from scratch. *(Same instinct as rolling-window state and rolling DP: update what changed, never recompute the whole thing.)*
* **5. Hot-loop discipline.** Use flat, preallocated structures for cache locality; allocate **zero** new objects inside the simulation tick; and decouple the fixed-timestep **simulation** from the **render** frame so physics stays deterministic regardless of frame rate. *(Same instinct as preferring iterative over recursive and keeping the inner loop flat.)*
* **6. Concurrency without bottlenecks.** Model the server as a single-loop **async event broker** (`asyncio`): non-blocking I/O, no thread-per-connection. This satisfies the "matchmaking broker, high concurrency, no latency bottleneck" requirement (Section 5) without lock contention or the GIL fighting you.
* **7. Fuzz the fast path against an oracle.** Keep a naive, obviously-correct reference for move legality and collision, and fuzz the bitboard implementation against it over tens of thousands of random positions. *(This is exactly the brute-force-oracle verification protocol, applied to the engine instead of a single problem.)*

**Correctness gate:** On UltraCode, exactly-matching output and an 80%+ score come first (Section 2). Optimize the hot path aggressively, but keep the `stdin`/`stdout` boundary dead-simple and never let an optimization change a byte of graded output.
## 9. Clean-Code & Extensibility Contract (Iteration 2+)

These are review-blocking requirements, learned from instructor feedback.

* **Rules are data, not code.** Piece identity and movement live in `Config`
  as data. The engine *interprets* a rule; it must NEVER branch on a concrete
  piece type (`if piece == 'R'`). This is what keeps user-defined games
  ("Shlomi's chess", e.g. a pawn that reverses instead of promoting) possible.
* **No hardcoded constants or strings in business logic.** Cell size, piece
  letters, colors, and error strings all sit in configuration/named constants.
* **Encapsulation.** No class reaches into another's internal storage. The
  board is accessed only via `piece_at` / `move` / `render`, so it can later
  become a bitboard with zero changes elsewhere.
* **DRY / SRP.** Each piece of logic exists in exactly one place; each function
  does one thing.
* **Testing.** Dependency injection only — NO monkeypatching (that mutates the
  code under test at runtime). Inject I/O via `run(inp, out)`. Target 100%
  coverage on `main.py`. Report: `python -m coverage run -m unittest discover`
  then `python -m coverage html`.
* **Environment.** Windows PowerShell: use `;` not `&&`, and `python -m coverage`.