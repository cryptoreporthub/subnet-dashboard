# Gameplan — Phase N (Accuracy & Calibration) & Phase O (Alerts, Reports & Launch-Readiness)

**Status:** APPROVED 2026-07-15 · Agents: A (`-843d`), B (`-e78a`)
**Models:** Composer **2.5** (default build) · Cursor Grok **slow + medium** default (escalate to **high** only if medium fails or is unsatisfactory)
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
Both agents run **one** shared design pass to lock N + O architecture and emit a written spec (saved as `cursor-agents-communication/phase-n-o-step0-spec.md`). **Start on slow Grok + medium thinking.** Escalate that same kickoff to **high** only if medium returns FAIL/CONDITIONAL or the output is unsatisfactory. Composer 2.5 implements only after the spec is written. Resolve: module boundaries, shared `server.py` router contracts, merge order, and the N1 `internal/council/*` allowlist.

## 3. Agent A slices
**N2 — Scenario-memory outcome wiring** (Composer 2.5; pattern exists from Phase J replay)
- Close prediction↔actual loop; today scenario-memory outcomes are blank (`—`).
- Files: `internal/learning/*` (outcome writer/persistence), `internal/council/*` (consume).
- AC: every resolved prediction writes an outcome row; scenario-memory UI shows non-blank outcomes; covered by `test_phase_j_*` extension or new `test_scenario_memory.py`.
- Verify: `pytest`; Fly `/api/learning/stats` shows outcomes.

**N3 — Calibration / retrain scheduler** (**Grok slow-medium design → Composer 2.5 wire**; escalate high only if needed)
- Periodic retrain → certify → fire pipeline for council models. Inventory existing `internal/calibration/` before rebuilding.
- Files: `internal/learning/*` (retrain job), `internal/scheduler.py` (cron hook), `fly.toml` (config only, no volume).
- AC: retrain on schedule; certified artifact; models updated behind flag; inference never blocked.
- Verify: `pytest`; dry-run scheduler; **Grok slow-medium hot-path safety review before merge** (escalate to high only on FAIL/unsatisfactory).

**O1 — Conviction-threshold alerts (backend)** (**Grok slow-medium design → Composer 2.5**; new subsystem)
- Notify on conviction thresholds (email + Telegram).
- Files: extend `internal/signals/alerts.py` AlertEngine **or** thin `internal/conviction_alerts/*`; routes `POST/GET /api/conviction-alerts/*` (NOT `/api/alerts`); guarded `include_router` + CONTRACT add.
- AC: opt-in/config-gated; idempotent; no spam; 200; contract test added.
- Verify: `pytest`; manual `POST /api/conviction-alerts/notify`.

**O4 — Custom domain + CDN** (Composer 2.5; config/docs)
- Move off `fly.dev`; CDN for static assets.
- Files: `fly.toml` (headers/cache), `DEPLOY.md` (DNS steps). DNS done by human.
- AC: `fly.toml` documents CDN/DNS; **no Fly volume created** (no token).

**O5 — Docs/handoff refresh** (Composer 2.5)
- Files: `docs/*`, `AGENTS.md`, `master-plan-merged.md`, `model-guide.md`.
- AC: plan reflects A+B split; model-guide §2/§4 updated to Composer 2.5 + A/B.

## 4. Agent B slices
**N1 — Oracle / grader tuning** (**Grok slow-medium design → Composer 2.5**; escalate high only if needed)
- Lift Oracle/Echo/Pulse win rate above ~45.5%.
- Files: `internal/oracle/*` (signal quality); grader/resolver touch only via Step 0 allowlist (A owns `internal/council/*`).
- AC: measurable win-rate lift on N4 backtest; no threshold gaming; honest-empty preserved.

**N4 — Backtest harness + analytics** (**Grok slow-medium design → Composer 2.5**; new subsystem)
- Honestly measure signal quality.
- Files: `internal/analytics/*` (backtest engine), new `tests/test_backtest.py`.
- AC: reproducible backtest of Oracle/Echo/Pulse → win-rate/calibration; tests pass.

**O2 — Backtest history UI** (Composer 2.5 build + **Grok slow-medium sign-off**)
- Surface backtest results in dashboard.
- Files: `templates/*`, `static/js/*`.
- AC: renders real payloads or explicit empty; zero `###` in rendered `/`; 12 frozen Cockpit section IDs untouched.

**O3 — Exportable per-subnet report** (Composer 2.5)
- Export a subnet's full analysis (PDF/markdown).
- Files: `internal/analytics/*` (builder), `templates/*` (view), `server.py` include_router.
- AC: `/api/report/<netuid>`-style endpoint; contract test added; honest-empty.

## 5. Model selection — Composer 2.5 vs Cursor Grok (slow-medium default)
**Composer 2.5 = default** for both agents. Use for: implementation once spec/path owned; porting existing patterns; REST routes, templates, CSS, JS; CI/contract tests; board/docs; hooks; non-behavioral <500-line changes.

**Cursor Grok — thinking policy (mandatory):**
1. Every Grok call starts **slow + medium** (not fast, not high, not xhigh).
2. Escalate to **high** only when medium returns FAIL/CONDITIONAL or the output is not satisfactory.
3. Never open xhigh or fast-xhigh by default. Fast variant only for light chores when able.
4. Prefer scoped read-only Grok subagents (Task tool) over switching the whole Cloud Agent run to Grok.

**Per-slice gate:**
| Slice | Sequence |
|---|---|
| Step 0 | Grok slow-medium kickoff → escalate **high** only if FAIL/unsatisfactory |
| N2 | Composer 2.5 |
| N3 | Grok slow-medium → Composer 2.5 (escalate high only if needed) |
| O1 | Grok slow-medium → Composer 2.5 |
| O4 | Composer 2.5 |
| O5 | Composer 2.5 |
| N1 | Grok slow-medium → Composer 2.5 (escalate high only if needed) |
| N4 | Grok slow-medium → Composer 2.5 |
| O2 | Composer 2.5 + Grok slow-medium sign-off |
| O3 | Composer 2.5 |

**Switch to Grok mid-session when:** "why?" debugging after a Composer fix; competing branches; new subsystem with no repo pattern; pre-merge behavioral review >500 lines; user asks "is this still correct?" — always start that Grok pass **slow + medium**.
**Do NOT switch for:** CSS polish, contract-test route adds, board/docs, merge/rebase, STATUS posts.

## 6. Sequencing & gates
- N ∥ O parallel (disjoint dirs).
- **Conflict surface:** `server.py` include_router + `tests/test_endpoint_contract.py` — both add routes; **rebase before merge; first merge wins.**
- Every new route → `tests/test_endpoint_contract.py` CONTRACT list (Deploy Guard blocks regressions).
- Pre-merge: `pytest` (phase + contract) + `mypy --strict` (best-effort on touched modules).

## 7. Non-negotiables
1. Honest-empty > decorative > 500.
2. Never lower confidence thresholds to fake accuracy.
3. Zero `###` in rendered `/`.
4. SELL ALERT > HOT when both active.
5. No `data/*.json` churn committed.
6. Single foundation: no `server_original.py` / parallel `server/` package.

## 8. Agent prompts (copy-paste)

### Agent A
```
You are Agent A (`-843d`) on cryptoreporthub/subnet-dashboard (single FastAPI foundation: server.py).
Read first (git): cursor-agents-communication/gameplan-N-O.md, board.md, STATUS.md, model-guide.md, master-plan-merged.md, docs/sciweave-answers-phase-j.md.

MODELS: Default build = Composer 2.5. GROK: every Grok call = slow + medium first. Escalate to high ONLY when medium fails or is unsatisfactory (N3 hot-path is a usual escalate candidate). Prefer Task subagent over switching the whole run.
STEP 0: DONE — read `cursor-agents-communication/phase-n-o-step0-spec.md` (binding). Start building now.

YOUR SLICES (start with N2):
- N2 Scenario-memory outcome wiring (Composer 2.5) — FIRST — internal/learning/* ; backfill blank outcomes; ensure scenario_id on create; no blank outcomes in UI.
- N3 Calibration/retrain scheduler (Grok slow-medium design → Composer 2.5 wire; escalate high only if needed) — inventory internal/calibration/ first; scheduler hook only; Grok slow-medium safety review before merge.
- O1 Conviction-threshold alerts backend (Grok slow-medium design → Composer 2.5) — `/api/conviction-alerts/*` per Step 0; extend AlertEngine; do NOT duplicate `/api/alerts`.
- O4 Custom domain + CDN (Composer 2.5) — fly.toml headers/cache + DEPLOY.md DNS. NO Fly volume (no token).
- O5 Docs/handoff (Composer 2.5) — docs/, AGENTS.md, master-plan-merged.md, model-guide.md.

OWNERSHIP: you OWN internal/learning/*, internal/council/*, internal/judges/*, fly.toml, DEPLOY.md, docs/. NEVER touch templates/*, static/*, internal/oracle/*, internal/analytics/*, internal/indicators/*.

CONSTRAINTS: every new route → tests/test_endpoint_contract.py CONTRACT; honest-empty > decorative > 500; never fake accuracy; no data/*.json churn; single foundation. Conflict with B on server.py + contract test: rebase before merge, first merge wins.
VERIFY: pytest (your phase + contract); mypy --strict best-effort. Update board.md + STATUS.md on PR open/merge. Report PR numbers + slices.
```

### Agent B
```
You are Agent B (`-e78a`) on cryptoreporthub/subnet-dashboard (single FastAPI foundation: server.py).
Read first (git): cursor-agents-communication/gameplan-N-O.md, board.md, STATUS.md, model-guide.md, master-plan-merged.md, docs/sciweave-answers-phase-j.md.

MODELS: Default build = Composer 2.5. GROK: every Grok call = slow + medium first. Escalate to high ONLY when medium fails or is unsatisfactory (N1 grader root-cause is a usual escalate candidate). Prefer Task subagent over switching the whole run.
STEP 0: DONE — read `cursor-agents-communication/phase-n-o-step0-spec.md` (binding). Start building now. Order: N4 → N1 → O2 → O3.

YOUR SLICES (start with N4):
- N4 Backtest harness + analytics (Grok slow-medium design → Composer 2.5) — FIRST — internal/analytics/backtest.py + tests/test_backtest.py + GET /api/backtest; CONTRACT; reproducible Oracle/Echo/Pulse backtest.
- N1 Oracle/grader tuning (Grok slow-medium design → Composer 2.5 wire; escalate high only if needed) — after N4 — internal/oracle/* + oracle_judge.py; council grader only via Step 0 allowlist (A lands grading.py/resolver.py); lift ~45.5% win rate; no threshold gaming.
- O2 Backtest history UI (Composer 2.5 build + Grok slow-medium sign-off) — after N4 — templates/*, static/js/* ; real payloads or explicit empty; zero ### in rendered /; 12 Cockpit IDs untouched.
- O3 Exportable per-subnet report (Composer 2.5) — internal/analytics/* builder + templates/* view + GET /api/report/{netuid}; contract test added.

OWNERSHIP: you OWN internal/oracle/*, internal/analytics/*, internal/indicators/*, templates/*, static/* . NEVER touch internal/learning/*, internal/council/*, internal/judges/*, fly.toml, DEPLOY.md, docs/.

CONSTRAINTS: every new route → tests/test_endpoint_contract.py CONTRACT; honest-empty > decorative > 500; never fake accuracy/backtests; no data/*.json churn; single foundation. Conflict with A on server.py + contract test: rebase before merge, first merge wins.
VERIFY: pytest (your phase + contract); mypy --strict best-effort. Update board.md + STATUS.md on PR open/merge. Report PR numbers + slices.
```
