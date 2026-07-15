# Gameplan — Phase N (Accuracy & Calibration) & Phase O (Alerts, Reports & Launch-Readiness)

**Status:** APPROVED 2026-07-15 · Agents: A (`-843d`), B (`-e78a`)
**Models:** Composer **2.5** (default build) · Cursor Grok **token-save first** (`grok-4.5-fast-xhigh` for every Grok call; escalate to `grok-4.5-xhigh` only after FAIL/CONDITIONAL)
**Repo:** cryptoreporthub/subnet-dashboard — single FastAPI foundation (`server.py`)
**Read first (git):** `board.md`, `STATUS.md`, `model-guide.md`, `master-plan-merged.md`, `docs/sciweave-answers-phase-j.md`, `concurrent-protocol.md`

## 0. Why these phases
From the 07-11 audit and the user's "what's next" list: council signals (Oracle/Echo/Pulse) sit at ~45.5% win rate (barely above random); scenario-memory outcomes are blank; alerts, backtests, and exportable reports don't exist; the app still runs on `fly.dev`. **N** fixes signal quality + closes the feedback loop. **O** ships alerts, reports, a backtest view, and launch-readiness.

## 1. Agent assignment (two agents)
| Agent | Suffix | Owns | Builds |
|---|---|---|---|
| **A** | `-843d` | `internal/learning/*`, `internal/council/*`, `internal/judges/*`, `fly.toml`, `DEPLOY.md`, `docs/` | N2, N3, O1, O4, O5 |
| **B** | `-e78a` | `internal/oracle/*`, `internal/analytics/*`, `internal/indicators/*`, `templates/*`, `static/*` | N1, N4, O2, O3 |

Disjoint dirs ⇒ N ∥ O run in parallel.

## 1.5 Pre-flight conflicts — Step 0 must resolve
The following are known from review; the Step 0 kickoff must produce **written decisions** for each (recorded in `cursor-agents-communication/phase-n-o-step0-spec.md`) before any Composer build:

1. **N1 ownership clash** — B needs grader/resolver work, but A owns `internal/council/*`. Decide: A-implemented-from-B-design via an allowlist, or narrow shared surface. (N1 council grader only via Step 0 allowlist.)
2. **Double "Phase O"** — `cursor-agents-communication/phase-o-design.md` describes an OLD Phase O = "TAO Signal Hub → Council" (creates `internal/signal_hub/`, `/api/signal-hub/*`) that is **COMPLETE / SUPERSEDED**. It is **not** this plan's O. Do **not** rebuild `internal/signal_hub/` or `/api/signal-hub/*`. New Phase O (this plan) = Alerts / Reports / Launch only. Mark old O docs superseded.
3. **Not greenfield** — `main` already has `internal/calibration/`, `/api/calibration/*`, Phase L `/api/alerts`, and `scenario_memory` `record_outcome` (many outcomes still blank). Inventory existing gaps before rebuild.
4. **O1 route collision** — `/api/alerts` already exists (Phase L). Use a distinct path/module or extend `AlertEngine`; do not duplicate. Grep `server.py` first.
5. **B sequencing** — N1 AC depends on N4 backtest; O2 needs N4 payloads. Suggested B order: **N4 → N1 → O2 → O3**.
6. **Conflict surface** — `server.py` `include_router` + `tests/test_endpoint_contract.py`; rebase before merge; first merge wins.
7. **Step 0 process** — one shared written spec both agents sign; not two unreconciled Grok passes.
8. **Pre-boot sync** — merge PR #221 (gameplan + board/STATUS/model-guide) and confirm the token-save commit `f03374b` is on `main`, so STATUS/board/gameplan match before A/B boot.

## 2. Step 0 — joint Grok kickoff (BEFORE any build)
Both agents run **one** shared design pass to lock N + O architecture and emit a written spec (saved as `cursor-agents-communication/phase-n-o-step0-spec.md`). **Start on `grok-4.5-fast-xhigh` (token-save).** Escalate that same kickoff to `grok-4.5-xhigh` only if the fast pass returns FAIL/CONDITIONAL with unresolved module-boundary or hot-path risk. Composer 2.5 implements only after the spec is written. Resolve: module boundaries, shared `server.py` router contracts, merge order, and the N1 `internal/council/*` allowlist.