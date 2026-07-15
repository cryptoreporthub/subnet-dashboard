# Phase N/O — Agent start prompts

**Saved:** 2026-07-15 · **Binding spec:** `phase-n-o-step0-spec.md` (LOCKED)

---

## Agent B (`-e78a`)

You are Agent B (`-e78a`) on cryptoreporthub/subnet-dashboard (single FastAPI foundation: `server.py`).

Read first (git): `cursor-agents-communication/gameplan-N-O.md`, `board.md`, `STATUS.md`, `model-guide.md`, `master-plan-merged.md`, `docs/sciweave-answers-phase-j.md`.

**MODELS:** Default build = Composer 2.5. GROK: every Grok call = slow + medium first. Escalate to high ONLY when medium fails or is unsatisfactory (N1 grader root-cause is a usual escalate candidate). Prefer Task subagent over switching the whole run.

**STEP 0:** DONE — read `cursor-agents-communication/phase-n-o-step0-spec.md` (binding). Start building now. Order: **N4 → N1 → O2 → O3**.

### YOUR SLICES (start with N4)

- **N4** Backtest harness + analytics (Grok slow-medium design → Composer 2.5) — FIRST — `internal/analytics/backtest.py` + `tests/test_backtest.py` + `GET /api/backtest`; CONTRACT; reproducible Oracle/Echo/Pulse backtest.
- **N1** Oracle/grader tuning (Grok slow-medium design → Composer 2.5 wire; escalate high only if needed) — after N4 — `internal/oracle/*` + `oracle_judge.py`; council grader only via Step 0 allowlist (A lands `grading.py`/`resolver.py`); lift ~45.5% win rate; no threshold gaming.
- **O2** Backtest history UI (Composer 2.5 build + Grok slow-medium sign-off) — after N4 — `templates/*`, `static/js/*`; real payloads or explicit empty; zero `###` in rendered `/`; 12 Cockpit IDs untouched.
- **O3** Exportable per-subnet report (Composer 2.5) — `internal/analytics/*` builder + `templates/*` view + `GET /api/report/{netuid}`; contract test added.

**OWNERSHIP:** you OWN `internal/oracle/*`, `internal/analytics/*`, `internal/indicators/*`, `templates/*`, `static/*`. NEVER touch `internal/learning/*`, `internal/council/*`, `internal/judges/*` except `oracle_judge.py` (N1), `fly.toml`, `DEPLOY.md`, `docs/`.

**CONSTRAINTS:** every new route → `tests/test_endpoint_contract.py` CONTRACT; honest-empty > decorative > 500; never fake accuracy/backtests; no `data/*.json` churn; single foundation. Conflict with A on `server.py` + contract test: rebase before merge, first merge wins.

**VERIFY:** pytest (your phase + contract); mypy --strict best-effort. Update `board.md` + `STATUS.md` on PR open/merge. Report PR numbers + slices.

---

## Agent A (`-843d`)

See `gameplan-N-O.md` §8 Agent A block. Slices: N2 → N3 → O1 → O4 → O5.
