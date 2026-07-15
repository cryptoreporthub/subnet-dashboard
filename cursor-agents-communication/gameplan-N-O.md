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

## 2. Step 0 — joint Grok kickoff (BEFORE any build)
Both agents run **one** shared design pass to lock N + O architecture and emit a written spec (saved as a PR comment or appended here). **Start on `grok-4.5-fast-xhigh` (token-save).** Escalate that same kickoff to `grok-4.5-xhigh` only if the fast pass returns FAIL/CONDITIONAL with unresolved module-boundary or hot-path risk. Composer 2.5 implements only after the spec is written. Resolve: module boundaries, shared `server.py` router contracts, merge order, and the N1 `internal/council/*` allowlist.

## 3. Agent A slices
**N2 — Scenario-memory outcome wiring** (Composer 2.5; pattern exists from Phase J replay)
- Close prediction↔actual loop; today scenario-memory outcomes are blank (`—`).
- Files: `internal/learning/*` (outcome writer/persistence), `internal/council/*` (consume).
- AC: every resolved prediction writes an outcome row; scenario-memory UI shows non-blank outcomes; covered by `test_phase_j_*` extension or new `test_scenario_memory.py`.
- Verify: `pytest`; Fly `/api/learning/stats` shows outcomes.

**N3 — Calibration / retrain scheduler** (**Grok-fast design → Composer 2.5 wire**; escalate xhigh only if needed)
- Periodic retrain → certify → fire pipeline for council models. Inventory existing `internal/calibration/` before rebuilding.
- Files: `internal/learning/*` (retrain job), `internal/scheduler.py` (cron hook), `fly.toml` (config only, no volume).
- AC: retrain on schedule; certified artifact; models updated behind flag; inference never blocked.
- Verify: `pytest`; dry-run scheduler; **Grok-fast hot-path safety review before merge** (escalate to xhigh only on FAIL/CONDITIONAL).

**O1 — Conviction-threshold alerts (backend)** (**Grok-fast design → Composer 2.5**; new subsystem)
- Notify on conviction thresholds (email + Telegram).
- Files: new `internal/alerts/*`, `server.py` guarded `include_router`, add `/api/alerts` to `tests/test_endpoint_contract.py`.
- AC: opt-in/config-gated; idempotent; no spam; 200; contract test added.
- Verify: `pytest`; manual `/api/alerts` POST.

**O4 — Custom domain + CDN** (Composer 2.5; config/docs)
- Move off `fly.dev`; CDN for static assets.
- Files: `fly.toml` (headers/cache), `DEPLOY.md` (DNS steps). DNS done by human.
- AC: `fly.toml` documents CDN/DNS; **no Fly volume created** (no token).

**O5 — Docs/handoff refresh** (Composer 2.5)
- Files: `docs/*`, `AGENTS.md`, `master-plan-merged.md`, `model-guide.md`.
- AC: plan reflects A+B split; model-guide §2/§4 updated to Composer 2.5 + A/B.

## 4. Agent B slices
**N1 — Oracle / grader tuning** (**Grok-fast design → Composer 2.5**; escalate xhigh only if needed)
- Lift Oracle/Echo/Pulse win rate above ~45.5%.
- Files: `internal/oracle/*` (signal quality); grader/resolver touch only via Step 0 allowlist (A owns `internal/council/*`).
- AC: measurable win-rate lift on N4 backtest; no threshold gaming; honest-empty preserved.

**N4 — Backtest harness + analytics** (**Grok-fast design → Composer 2.5**; new subsystem)
- Honestly measure signal quality.
- Files: `internal/analytics/*` (backtest engine), new `tests/test_backtest.py`.
- AC: reproducible backtest of Oracle/Echo/Pulse → win-rate/calibration; tests pass.

**O2 — Backtest history UI** (Composer 2.5 build + **Grok-fast sign-off**)
- Surface backtest results in dashboard.
- Files: `templates/*`, `static/js/*`.
- AC: renders real payloads or explicit empty; zero `###` in rendered `/`; 12 frozen Cockpit section IDs untouched.

**O3 — Exportable per-subnet report** (Composer 2.5)
- Export a subnet's full analysis (PDF/markdown).
- Files: `internal/analytics/*` (builder), `templates/*` (view), `server.py` include_router.
- AC: `/api/report/<netuid>`-style endpoint; contract test added; honest-empty.

## 5. Model selection — Composer 2.5 vs Cursor Grok (token-save)
**Composer 2.5 = default** for both agents. Use for: implementation once spec/path owned; porting existing patterns; REST routes, templates, CSS, JS; CI/contract tests; board/docs; hooks; non-behavioral <500-line changes.

**Cursor Grok — token-save policy (mandatory):**
1. Every Grok call starts on **`grok-4.5-fast-xhigh`** (design, audit, Step 0, N3/N1, sign-off).
2. Escalate to **`grok-4.5-xhigh` only** when that fast pass returns **FAIL/CONDITIONAL** with unresolved behavioral/hot-path risk (typical candidates: N3 retrain, N1 grader root-cause).
3. Never open a full-xhigh run “just in case.” Never use full xhigh for O4/O5/N2/O3, board/docs, or routine sign-offs.
4. Prefer scoped read-only Grok subagents (Task tool) over switching the whole Cloud Agent run to Grok.

**Per-slice gate:**
| Slice | Sequence |
|---|---|
| Step 0 | Grok-fast kickoff → escalate xhigh only if FAIL/CONDITIONAL |
| N2 | Composer 2.5 |
| N3 | Grok-fast → Composer 2.5 (escalate xhigh only if needed) |
| O1 | Grok-fast → Composer 2.5 |
| O4 | Composer 2.5 |
| O5 | Composer 2.5 |
| N1 | Grok-fast → Composer 2.5 (escalate xhigh only if needed) |
| N4 | Grok-fast → Composer 2.5 |
| O2 | Composer 2.5 + Grok-fast sign-off |
| O3 | Composer 2.5 |

**Switch to Grok mid-session when:** "why?" debugging after a Composer fix; competing branches; new subsystem with no repo pattern; pre-merge behavioral review >500 lines; user asks "is this still correct?" — always start that Grok pass on **fast-xhigh**.
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

MODELS: Default build = Composer 2.5. TOKEN-SAVE: every Grok call = grok-4.5-fast-xhigh first. Escalate to grok-4.5-xhigh ONLY when that fast pass returns FAIL/CONDITIONAL (N3 hot-path is the usual escalate candidate). Prefer Task subagent over switching the whole run.
STEP 0: Both agents run ONE shared Grok-fast kickoff to lock N+O architecture + emit written spec; escalate that kickoff to xhigh only if FAIL/CONDITIONAL. Do NOT build before this.

YOUR SLICES:
- N2 Scenario-memory outcome wiring (Composer 2.5) — internal/learning/* ; close prediction↔actual loop; no blank outcomes.
- N3 Calibration/retrain scheduler (Grok-fast design → Composer 2.5 wire; escalate xhigh only if needed) — inventory internal/calibration/ first; safe hot-path; Grok-fast safety review before merge.
- O1 Conviction-threshold alerts backend (Grok-fast design → Composer 2.5) — extend Phase L alerts or new path per Step 0; no duplicate /api/alerts collision.
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

MODELS: Default build = Composer 2.5. TOKEN-SAVE: every Grok call = grok-4.5-fast-xhigh first. Escalate to grok-4.5-xhigh ONLY when that fast pass returns FAIL/CONDITIONAL (N1 grader root-cause is the usual escalate candidate). Prefer Task subagent over switching the whole run.
STEP 0: Both agents run ONE shared Grok-fast kickoff to lock N+O architecture + emit written spec; escalate that kickoff to xhigh only if FAIL/CONDITIONAL. Do NOT build before this.

YOUR SLICES:
- N1 Oracle/grader tuning (Grok-fast design → Composer 2.5 wire; escalate xhigh only if needed) — internal/oracle/* ; council grader only via Step 0 allowlist; lift ~45.5% win rate; no threshold gaming.
- N4 Backtest harness + analytics (Grok-fast design → Composer 2.5) — internal/analytics/* + new tests/test_backtest.py ; reproducible Oracle/Echo/Pulse backtest (build before N1 AC depends on it).
- O2 Backtest history UI (Composer 2.5 build + Grok-fast sign-off) — templates/*, static/js/* ; real payloads or explicit empty; zero ### in rendered /; 12 Cockpit IDs untouched.
- O3 Exportable per-subnet report (Composer 2.5) — internal/analytics/* builder + templates/* view + server.py guarded include_router (e.g. /api/report/<netuid>); contract test added.

OWNERSHIP: you OWN internal/oracle/*, internal/analytics/*, internal/indicators/*, templates/*, static/* . NEVER touch internal/learning/*, internal/council/*, internal/judges/*, fly.toml, DEPLOY.md, docs/.

CONSTRAINTS: every new route → tests/test_endpoint_contract.py CONTRACT; honest-empty > decorative > 500; never fake accuracy/backtests; no data/*.json churn; single foundation. Conflict with A on server.py + contract test: rebase before merge, first merge wins.
VERIFY: pytest (your phase + contract); mypy --strict best-effort. Update board.md + STATUS.md on PR open/merge. Report PR numbers + slices.
```
