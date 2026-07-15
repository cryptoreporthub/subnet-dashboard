# Phase N/O — Step 0 Architecture Spec

**Status:** LOCKED 2026-07-15 · Agent `-6f98` (joint kickoff, Grok slow-medium)  
**main at kickoff:** `778ad13` (#221 merged)  
**Canonical plan:** `cursor-agents-communication/gameplan-N-O.md`  
**Models:** Composer 2.5 build · every Grok call = **slow + medium** · escalate to **high** only if medium fails or is unsatisfactory

Composer 2.5 may begin slices **only after** this file is on `main`. Escalate to **high** was **not** required — all pre-flight items resolved at medium.

---

## 0. Verdict

**PASS — architecture locked.** No unresolved module-boundary or hot-path ambiguity requiring escalate to **high**.

---

## 1. Pre-flight decisions (gameplan §1.5)

### 1.1 N1 ownership clash — **DECIDED: A-implements-from-B-design + allowlist**

| Role | Does |
|------|------|
| **B** | Designs N1 (Grok slow-medium). Implements **only** `internal/oracle/*` + `internal/judges/oracle_judge.py` (oracle scoring inputs). Writes N1 design note with proposed grader/resolver diffs. |
| **A** | Owns all `internal/council/*` edits. Implements B’s proposed grader/resolver changes from the design note. |

**Allowlist (B may propose; A must land):**

- `internal/council/grading.py`
- `internal/council/resolver.py` (grader call sites / outcome fields only — no scheduler rewrite)
- `internal/judges/oracle_judge.py` (B may edit directly — lives under judges; A owns dir but B is primary N1 implementer for this file)

**B must NEVER commit** direct edits under `internal/council/` without A co-own or A follow-up PR. Prefer: B PR for oracle + harness; A PR for council grader apply.

### 1.2 Double Phase O — **DECIDED: old O SUPERSEDED**

- `phase-o-design.md` = **OLD** “TAO Signal Hub → Council” — **COMPLETE on `main`** (`internal/signal_hub/`, `/api/signal-hub/*`). **Do not rebuild.**
- Banner added at top of `phase-o-design.md`.
- **New Phase O** (this plan) = Alerts / Reports / Launch only (O1–O5).

### 1.3 Gap inventory — **DECIDED: extend, don’t rebuild**

| Slice | State | Build what |
|-------|-------|------------|
| **N2** | PARTIAL | Resolver already calls `scenario_memory.record_outcome`. Fix blank historical rows: backfill from resolved predictions + ensure every create path sets `scenario_id`. Tests for non-blank UI. |
| **N3** | PARTIAL | Keep `internal/calibration/` pipeline + routes. Add env-gated scheduler/post-resolver hook only (`CALIBRATION_AUTO_RETRAIN`). No greenfield retrain rewrite. |
| **N1** | PARTIAL | `/api/oracle` is a stub; real signal in `internal/judges/oracle_judge.py` + council grading. Tune quality; measure via N4. |
| **N4** | MISSING | New `internal/analytics/backtest.py` (+ route) + `tests/test_backtest.py`. Reproducible Oracle/Echo/Pulse win-rate/calibration. |
| **O1** | PARTIAL | Phase L owns `/api/alerts`. Add conviction notify on distinct routes (below). |
| **O2** | MISSING | Templates/static after N4 payloads exist. |
| **O3** | MISSING | `/api/report/{netuid}` (+ optional markdown/PDF view). |
| **O4** | PARTIAL | `fly.toml` + `DEPLOY.md` DNS/CDN docs; human does DNS. No Fly volume. |
| **O5** | PARTIAL | Refresh docs; mark old O superseded; sync board/STATUS. |
| **Old O hub** | COMPLETE | Leave alone. |

### 1.4 O1 route collision — **DECIDED: distinct routes, extend AlertEngine**

- **Keep** Phase L `GET/POST /api/alerts` unchanged.
- **O1 adds:**
  - `POST /api/conviction-alerts/notify` — evaluate conviction thresholds; create alerts via existing `AlertEngine` (store/dedupe/webhook).
  - `GET /api/conviction-alerts/status` — config + last-run (honest-empty).
- Module: prefer thin `internal/conviction_alerts/` that **imports** `internal.signals.alerts.AlertEngine` — do **not** invent a second alert store.
- CONTRACT: add the two new routes; do **not** re-add `/api/alerts`.

### 1.5 B sequencing — **DECIDED: N4 → N1 → O2 → O3**

N1 AC needs N4 backtest numbers; O2 needs N4 payloads. A may run N2 ∥ N3 ∥ O1 in parallel with B’s N4.

### 1.6 Conflict surface — **DECIDED**

- Shared: `server.py` `include_router` + `tests/test_endpoint_contract.py` only.
- Rebase before merge; first merge wins.
- Prefer mounting new routers from owned packages (`learning_router`, `analytics_router`, `signals_router`) to minimize `server.py` churn.

### 1.7 Step 0 process — **DECIDED**

This file is the single shared signed spec. A/B treat it as binding; no second unreconciled Grok kickoff.

### 1.8 Pre-boot sync — **DONE**

PR #221 merged to `main` @ `778ad13` (includes token-save `f03374b` + pre-flight §1.5).

---

## 2. Module boundaries

| Agent | Owns | Builds now |
|-------|------|------------|
| **A** `-843d` | `internal/learning/*`, `internal/council/*`, `internal/judges/*` (except B’s direct N1 work on `oracle_judge.py`), `internal/calibration/*`, `internal/conviction_alerts/*`, `fly.toml`, `DEPLOY.md`, `docs/`, board/STATUS on own merges | N2, N3, O1, O4, O5 |
| **B** `-e78a` | `internal/oracle/*`, `internal/analytics/*`, `internal/indicators/*`, `templates/*`, `static/*`, `internal/judges/oracle_judge.py` (N1) | N4 → N1 → O2 → O3 |

**Neither agent** rebuilds `internal/signal_hub/` or changes frozen Cockpit section IDs (12).

---

## 3. Router / CONTRACT contracts

| Slice | Routes | Mount via |
|-------|--------|-----------|
| N2 | existing `/api/scenario-memory` — no new route required unless backfill endpoint added | learning |
| N3 | existing `/api/calibration/status`, `/api/calibration/retrain` — scheduler is env hook, not new route | learning/calibration |
| N4 | `GET /api/backtest` (+ optional `POST /api/backtest/run`) | analytics |
| N1 | existing `/api/oracle` enriched; no mandatory new route | oracle |
| O1 | `GET /api/conviction-alerts/status`, `POST /api/conviction-alerts/notify` | conviction_alerts → signals or server include |
| O2 | UI only (consume N4 JSON); optional hydrate binder | templates/static |
| O3 | `GET /api/report/{netuid}` | analytics |
| O4/O5 | docs/config only | — |

Every new route → `tests/test_endpoint_contract.py` CONTRACT.

---

## 4. Merge order (recommended)

1. **B: N4** backtest harness (unblocks N1 AC + O2)
2. **A: N2** scenario outcome backfill/wiring (independent)
3. **A: N3** calibration scheduler hook (independent; Grok slow-medium safety before merge)
4. **B: N1** oracle tuning (after N4)
5. **A: O1** conviction alerts (independent of B after Step 0 route lock)
6. **B: O2** backtest UI (after N4)
7. **B: O3** report API
8. **A: O4** then **O5** (docs last so they reflect shipped reality)

Parallel OK: A(N2∥N3∥O1) while B(N4). Serialize when both touch CONTRACT/`server.py`.

---

## 5. Non-negotiables (reaffirmed)

1. Honest-empty > decorative > 500  
2. Never lower confidence thresholds to fake accuracy  
3. Zero `###` in rendered `/`  
4. SELL ALERT > HOT when both active  
5. No `data/*.json` churn committed  
6. Single foundation (`server.py` only)  
7. Grok: slow + medium default; escalate to high only if medium fails / unsatisfactory  

---

## 6. Agent start checklist

**Before first Composer PR:**

- [x] #221 on `main`
- [x] This Step 0 spec written
- [ ] This Step 0 PR merged to `main`
- [ ] Board/STATUS show Step 0 LOCKED + A/B unblocked

**A first PR candidates:** N2 backfill/tests  
**B first PR candidates:** N4 `internal/analytics/backtest.py` + CONTRACT

---

## 7. Sign-off

| Item | Result |
|------|--------|
| Step 0 model | Grok slow + medium (no escalate to high) |
| Architecture | LOCKED |
| Composer build | **UNBLOCKED** after this file merges |
| Escalation to high | Not required |
