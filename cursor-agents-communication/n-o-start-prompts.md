# Phase N/O — Agent start prompts

**Saved:** 2026-07-15 · **Binding spec:** `phase-n-o-step0-spec.md` (LOCKED)  
**Grok policy:** slow + medium first (per PR #225); do NOT revert PR #221/#223/#224/#225/#226 or Step 0 spec.

---

## Agent A (`-843d`)

You are Agent A (`-843d`) on cryptoreporthub/subnet-dashboard (single FastAPI foundation: `server.py`).

Read first (git): `gameplan-N-O.md`, `board.md`, `STATUS.md`, `model-guide.md`, `master-plan-merged.md`, `phase-n-o-step0-spec.md`.

**MODELS:** Default build = Composer 2.5. Grok = slow + medium first; escalate to **high** only if medium fails or is unsatisfactory (N3 hot-path is the usual escalate candidate).

**SLICES:** N2 → N3 ∥ O1 → O4 → O5

- **N2** Scenario outcome backfill — `internal/learning/scenario_outcomes.py`, `tests/test_scenario_memory.py`
- **N3** Calibration post-resolver hook — `CALIBRATION_AUTO_RETRAIN`, `internal/calibration/scheduler.py`
- **O1** Conviction alerts — `GET/POST /api/conviction-alerts/*` via `AlertEngine`
- **O4** Custom domain + CDN — `fly.toml`, `DEPLOY.md`
- **O5** Docs refresh — `AGENTS.md`, `master-plan-merged.md`, board/STATUS

**OWNERSHIP:** `internal/learning/*`, `internal/council/*`, `internal/judges/*`, `internal/calibration/*`, `internal/conviction_alerts/*`, `fly.toml`, `DEPLOY.md`, `docs/`. Never touch `templates/*`, `static/*`, `internal/oracle/*`, `internal/analytics/*`, `internal/indicators/*`.

**STATUS (2026-07-15):** Delivered in PR **#227** — rebase onto `main` after B **#228**, then merge.

---

## Agent B (`-e78a`)

You are Agent B (`-e78a`) on cryptoreporthub/subnet-dashboard (single FastAPI foundation: `server.py`).

Read first (git): `gameplan-N-O.md`, `board.md`, `STATUS.md`, `model-guide.md`, `phase-n-o-step0-spec.md`.

**MODELS:** Default build = Composer 2.5. Grok = slow + medium first; escalate to **high** only if medium fails or is unsatisfactory (N1 grader root-cause is the usual escalate candidate).

**STRICT SEQUENCE:** N4 → N1 → O2 → O3

- **N4** Backtest — `internal/analytics/backtest.py`, `GET /api/backtest`
- **N1** Oracle/grader tuning — `internal/oracle/*`, `oracle_judge.py`
- **O2** Backtest history UI — `templates/*`, `static/js/*`
- **O3** Per-subnet report — `GET /api/report/{netuid}`

**OWNERSHIP:** `internal/oracle/*`, `internal/analytics/*`, `internal/indicators/*`, `templates/*`, `static/*`, `oracle_judge.py`. Never touch `internal/learning/*`, `internal/council/*` (except N1 allowlist via A), `fly.toml`, `DEPLOY.md`.

**STATUS (2026-07-15):** ✅ **#228 merged** on `main`.
