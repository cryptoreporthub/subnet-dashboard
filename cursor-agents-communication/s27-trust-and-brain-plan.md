# §27 — Trust shell + data truth + brain visible

**Status:** APPROVED — ready to build  
**Updated:** 2026-07-17  
**Baseline:** `main` post-#307 (`f35e5a6`)  
**Human sequencing:** **§27-1 → §27-2 first** (finished product feel). **§27-3** (Tier 3) after §27-1 trust shell is live. **§28** deferred until product is share-ready.

**Models:** Composer 2.5 build · Grok subagent slow+low/med for IA/DESIGN on §27-3 only if ambiguous.

---

## Why §27 exists

§21–§26 shipped trust *banner* and Living Brain narrative, but production still shows:

- `REGISTRY-FALLBACK` first paint + perpetual “Loading…” / “warming up” panels
- Signals/alerts/KPI at 0 while APIs return hundreds of rows
- Conflicting accuracy (hero trust vs KPI strip vs portfolio P&L)
- `merged_data` (Blockmachine + TaoStats + TMC) wired for judges only — not `/api/subnets` / homepage hydrate
- Pro/Market drawers bury judges, weights, investigation (§17 U1 demotion — revisit selectively in §27-3)

---

## Queue (sequential)

| # | Slice | Goal | Stop human? |
|---|-------|------|-------------|
| **§27-1** | **Trust shell** | Kill loading theater: hydrate signals, alerts, KPI from real APIs; honest LIVE/STALE from `/api/data-freshness`; single trust number (banner = KPI = learning-metrics) | No |
| **§27-2** | **Data pipeline** | Route `/api/subnets` + hydrate source labels through merged/live path; fix `cockpit_hydrate.js` hardcoded TAOMARKETCAP when chain is primary | No |
| **§27-3** | **Brain visible (Tier 3)** | Judges↔hero netuid; open brain bench (weights + 3 judges); conviction peek; Labs 3 cards; investigation ask UX (tables not `<pre>`) | No |
| **§27-4** | **Learning hygiene** | Single `nudge_expert()` for resolver + `/api/feedback`; optional EMA only if batch calibration (§25) is too slow between retrains — **no Redis** | No |

**Skip unless asked:** Redis / Layer-Two cache · full Bittensor Python SDK · metagraph reads without a product feature

---

## §27-1 — Trust shell (AC)

- [ ] Homepage panels show real counts from `/api/signals/summary`, `/api/alerts`, `/api/learning-metrics` — not blocked on `/api/learning/stats` 503
- [ ] KPI strip hydrates same object as trust banner (`trust_banner` / `learning-metrics`)
- [ ] Header LIVE pill derives from `/api/data-freshness` (`LIVE` / `SNAPSHOT` / `STALE`) — never LIVE + stale simultaneously
- [ ] Portfolio panel uses slim `/api/portfolio/status`; scary aggregate P&L labeled or capped with context
- [ ] Fail closed: one honest banner, not 12 “warming up” cards

**Files (likely):** `server.py`, `static/js/cockpit_hydrate.js`, `static/js/trust_banner_ui.js`, `static/js/data_freshness.js`, `templates/partials/premium/kpi.html`, `signals.html`, `alerts.html`, `header.html`

---

## §27-2 — Data pipeline (AC)

- [ ] `/api/subnets` returns `sources: [blockmachine, …]` when chain feed is primary
- [ ] `get_all_subnets()` or `merged_data.get_merged_subnet_data()` is the single read path for API + picks (TMC overlay only when chain thin)
- [ ] UI data-source badge matches API `source` / `sources` — no false TAOMARKETCAP label when Blockmachine is live
- [ ] `verify_prod.sh` asserts non-empty subnet count + freshness when RPC healthy

**Files (likely):** `server.py`, `fetchers/taomarketcap.py`, `fetchers/merged_data.py`, `internal/live_subnets.py`, `static/js/cockpit_hydrate.js`

---

## §27-3 — Brain visible / Tier 3 (AC)

See **Tier 3 design** below. Builds on §27-1 (honest-empty rules).

- [ ] **Brain bench** (open, not in collapsed drawer): Oracle/Echo/Pulse for **hero netuid** via `/api/judges/{netuid}`; 4 expert weight bars from `/api/council/weights` or learning-metrics
- [ ] Story path step 2 relabeled “Council experts” OR shows Oracle/Echo/Pulse — no dual meaning of “judges”
- [ ] **Conviction peek:** top 3 SimiVision picks always visible (from `/api/simivision`)
- [ ] **Labs strip** (3 cards): scenario-memory + rotation · ruggers summary · postmortems + pump-analytics — honest-empty when inactive
- [ ] Investigation presets call `/api/investigate/ask` + owner-check; sellers/wallet as tables
- [ ] Pro drawer default-open on desktop OR summary shows live counts; Market drawer unchanged for tools

**Files (likely):** `templates/partials/premium_cockpit.html`, new `brain_bench.html`, `labs.html`, `static/js/premium_judges.js`, `investigation_panel.js`, `council_first.css`

**IA note:** Selectively **reverses §17 U1 demotion** for reasoning layer only — hero stays single-job; bench is “why this call,” not card sprawl.

---

## §27-4 — Learning hygiene (AC)

- [ ] `nudge_expert(expert, correct)` shared by `resolver._nudge_weights` and `LearningEngine.record_feedback`
- [ ] Phase N `run_calibration_pipeline` remains batch authority — no fourth weight path
- [ ] Optional: EMA on per-expert rolling hit rate (α≈0.15) inside `nudge_expert` — only if unified + tested
- [ ] Trail/UI emits weight change on resolve (brain bench can show “last nudge”)

**Files (likely):** `internal/council/weights.py`, `internal/council/resolver.py`, `datastore/learning_engine.py`

---

## RF gates (unchanged)

- Trust surfaces bind `trust_banner` only (RF-2).
- Honest-empty > fake data.
- No Redis / no second server foundation.

## Contract

1. Branch `cursor/<slug>-c3fd` off latest `main`
2. Ready PR · merge when CI green · §27-1 before §27-3
3. No `data/*.json` commits · ponytail minimal diff
