# Gameplan — Phase N (Accuracy & Calibration) & Phase O (Alerts, Reports & Launch-Readiness)

**Status:** APPROVED 2026-07-15 · Agents: A (`-843d`), B (`-e78a`)
**Models:** Composer **2.5** (default build) · Cursor Grok (`grok-4.5-fast-xhigh` default for design/audit, `grok-4.5-xhigh` for high-risk N only)
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

## 2. Step 0 — joint Grok-xhigh kickoff (BEFORE any build)
Both agents run **one** `grok-4.5-xhigh` design pass to lock N + O architecture and emit a written spec (saved as a PR comment or appended here). Composer 2.5 implements only after the spec is written. Resolve: module boundaries, shared `server.py` router contracts, and merge order.

## 3. Agent A slices
**N2 — Scenario-memory outcome wiring** (Composer 2.5; pattern exists from Phase J replay)
- Close prediction↔actual loop; today scenario-memory outcomes are blank (`—`).
- Files: `internal/learning/*` (outcome writer/persistence), `internal/council/*` (consume).
- AC: every resolved prediction writes an outcome row; scenario-memory UI shows non-blank outcomes; covered by `test_phase_j_*` extension or new `test_scenario_memory.py`.
- Verify: `pytest`; Fly `/api/learning/stats` shows outcomes.

**N3 — Calibration / retrain scheduler** (**Grok-xhigh design → Composer 2.5 wire**; new subsystem)
- Periodic retrain → certify → fire pipeline for council models.
- Files: `internal/learning/*` (retrain job), `internal/scheduler.py` (cron hook), `fly.toml` (config only, no volume).
- AC: retrain on schedule; certified artifact; models updated behind flag; inference never blocked.
- Verify: `pytest`; dry-run scheduler; **Grok-xhigh hot-path safety review before merge**.

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
**N1 — Oracle / grader tuning** (**Grok-xhigh design → Composer 2.5**; accuracy risk)
- Lift Oracle/Echo/Pulse win rate above ~45.5%.
- Files: `internal/oracle/*` (signal quality), `internal/council/*` grader/resolver.
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

## 5. Model selection — Composer 2.5 vs Cursor Grok
**Composer 2.5 = default** for both agents. Use for: implementation once spec/path owned; porting existing patterns; REST routes, templates, CSS, JS; CI/contract tests; board/docs; hooks; non-behavioral <500-line changes.

**Cursor Grok** (via Task subagent or model picker):
- `grok-4.5-fast-xhigh` — **default Grok**: design spikes, audits, pre-merge sign-offs (token-efficient).
- `grok-4.5-xhigh` — **only** high-risk architecture (N3 retrain, N1 resolver/grader root-cause) when fast pass returns FAIL/CONDITIONAL.

**Per-slice gate:**
| Slice | Sequence |
|---|---|
| N2 | Composer 2.5 |
| N3 | Grok-xhigh → Composer 2.5 |
| O1 | Grok-fast → Composer 2.5 |
| O4 | Composer 2.5 |
| O5 | Composer 2.5 |
| N1 | Grok-xhigh → Composer 2.5 |
| N4 | Grok-fast → Composer 2.5 |
| O2 | Composer 2.5 + Grok-fast sign-off |
| O3 | Composer 2.5 |

**Switch to Grok mid-session when:** "why?" debugging after a Composer fix; competing branches; new subsystem with no repo pattern; pre-merge behavioral review >500 lines; user asks "is this still correct?"
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

MODELS: Default build = Composer 2.5. Grok via Task subagent/model picker: grok-4.5-fast-xhigh (default for design/audit/sign-off), grok-4.5-xhigh ONLY for high-risk N3 retrain architecture when fast pass returns FAIL/CONDITIONAL.
STEP 0: Both agents run ONE grok-4.5-xhigh kickoff to lock N+O architecture + emit written spec. Do NOT build before this.

YOUR SLICES:
- N2 Scenario-memory outcome wiring (Composer 2.5) — internal/learning/* ; close prediction↔actual loop; no blank outcomes.
- N3 Calibration/retrain scheduler (Grok-xhigh design → Composer 2.5 wire) — internal/learning/* + internal/scheduler.py ; safe hot-path; Grok-xhigh hot-path review before merge.
- O1 Conviction-threshold alerts backend (Grok-fast design → Composer 2.5) — new internal/alerts/* + server.py guarded include_router.
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

MODELS: Default build = Composer 2.5. Grok via Task subagent/model picker: grok-4.5-fast-xhigh (default for design/audit/sign-off), grok-4.5-xhigh ONLY for high-risk N1 resolver/grader root-cause when fast pass returns FAIL/CONDITIONAL.
STEP 0: Both agents run ONE grok-4.5-xhigh kickoff to lock N+O architecture + emit written spec. Do NOT build before this.

YOUR SLICES:
- N1 Oracle/grader tuning (Grok-xhigh design → Composer 2.5 wire) — internal/oracle/* + internal/council/* grader; lift ~45.5% win rate; no threshold gaming.
- N4 Backtest harness + analytics (Grok-fast design → Composer 2.5) — internal/analytics/* + new tests/test_backtest.py ; reproducible Oracle/Echo/Pulse backtest.
- O2 Backtest history UI (Composer 2.5 build + Grok-fast sign-off) — templates/*, static/js/* ; real payloads or explicit empty; zero ### in rendered /; 12 Cockpit IDs untouched.
- O3 Exportable per-subnet report (Composer 2.5) — internal/analytics/* builder + templates/* view + server.py guarded include_router (e.g. /api/report/<netuid>); contract test added.

OWNERSHIP: you OWN internal/oracle/*, internal/analytics/*, internal/indicators/*, templates/*, static/* . NEVER touch internal/learning/*, internal/council/*, internal/judges/*, fly.toml, DEPLOY.md, docs/.

CONSTRAINTS: every new route → tests/test_endpoint_contract.py CONTRACT; honest-empty > decorative > 500; never fake accuracy/backtests; no data/*.json churn; single foundation. Conflict with A on server.py + contract test: rebase before merge, first merge wins.
VERIFY: pytest (your phase + contract); mypy --strict best-effort. Update board.md + STATUS.md on PR open/merge. Report PR numbers + slices.
```
