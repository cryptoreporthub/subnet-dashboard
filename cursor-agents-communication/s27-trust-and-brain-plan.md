# §27 — Trust shell + data truth + brain visible

**Status:** APPROVED — ready to build  
**Updated:** 2026-07-17T14:10:00Z  
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

## §27-3 — Brain visible / Tier 3

Builds on §27-1 (honest-empty). **Three PRs:** §27-3a → §27-3b → §27-3c.

**IA note:** Selectively **reverses §17 U1 demotion** for the reasoning layer only — hero stays single-job; bench is “why this call,” not card sprawl.

### Cross-cutting: name integrity

- Every displayed subnet name: `enrich_subnet_row` / `resolve_subnet_name` at API boundary — **never hardcoded examples in templates**
- Hero netuid from `/api/daily-pick` (`pick.subnet.netuid` ?? `candidate.subnet.netuid`) — never assume SN1/Apex
- **Blocking:** fix `/api/simivision` top rows returning `SNNone` / null names before conviction peek ships
- Unresolved names (e.g. SN82 → `SN82`) show honestly; track resolver gaps separately

### §27-3a — Brain bench (judges ↔ hero + weights)

**Problem:** Story path step 2 says “Judges” but shows expert_contributions; `#section-judges` shows Oracle/Echo/Pulse for 12 unrelated subnets inside collapsed Pro drawer.

**Placement:** New `#section-brain-bench` after story-strip, before story-path.

**Hydrate (fast path — do not call `/api/judges` league table on home):**

```
GET /api/daily-pick          → hero_netuid, audited vs candidate-only
GET /api/judges/{hero_netuid} → oracle, echo, pulse, consensus
GET /api/calibration/status  → weights (quant/hype/dark_horse/technical)
```

**UI:** Three judge cells + four weight bars + consensus line. Candidate-only day: banner “Candidate · council audit pending” when `pick` is null but `candidate` exists.

**Story path:** Rename step 2 label `2 · Judges` → `2 · Council experts` in `story_path.py`. Optional step 2b from `/api/judges/{netuid}`.

**AC:**

- [ ] Bench visible without opening Pro drawer
- [ ] Scores match `/api/judges/{hero_netuid}`; weights match calibration (±0.001)
- [ ] `cockpit_hydrate.js` league-table judges demoted to Pro-only (or remove home fetch)
- [ ] New `brain_bench.js` — single-netuid fetch (~200ms), not 50-subnet `/api/judges`

**Files:** `brain_bench.html`, `brain_bench.js`, `premium_cockpit.html`, `story_path.py`, `story_path.html`, `cockpit_hydrate.js`, `council_first.css`

### §27-3b — Conviction peek + Labs strip

**2A — Conviction peek** (`#section-conviction-peek`): top 3 from `/api/simivision` with enriched names, recommendation, conviction, call_line. Link “Open full board → #pro-cockpit”. Click row → re-hydrate brain bench for that netuid (compare mode).

**2B — Labs strip** (`#section-labs`), three cards, honest-empty:

| Card | APIs | Shows |
|------|------|--------|
| Market memory | `/api/scenario-memory`, `/api/rotation-tracker` | Regime, scenario count, top vol cluster |
| Risk watch | `/api/ruggers/summary`, `/api/ruggers/subnet/{hero_netuid}` | Alerts, watchlist size, hero SN risk |
| Autopsy | `/api/postmortems`, `/api/pump-analytics` | Latest postmortem one-liner, pump phase count |

**Cross-wire:** If ruggers elevates hero subnet → amber chip on brain bench header.

**AC:**

- [ ] Simivision peek shows real names (not `SNNone`)
- [ ] Labs cards honest-empty when APIs inactive
- [ ] Hero netuid shared via `data-hero-netuid` on brain bench (used by Labs + investigation)

**Files:** `conviction_peek.html`, `labs_strip.html`, `labs_hydrate.js`, simivision route (name enrichment), `premium_cockpit.html`

### §27-3c — Investigation desk

**Problem:** `investigation_panel.js` dumps JSON to `<pre>`; presets only fill `#chatInput`.

**Modes:**

1. **Sellers table** — `GET /api/investigate/subnet/{netuid}/sellers` (columns: wallet, side, TAO, time, tx link)
2. **Wallet trace** — `GET /api/investigate/wallet/{ss58}/flow` (summary chips + table)
3. **Presets → API** — `POST /api/investigate/ask`; owner-check `GET .../owner-check?wallets=` from top sellers

Default `inv-netuid` = hero netuid (not hardcoded 82). Preset labels dynamic: “Who sold SN{n} {name}?”

Chat secondary (“explain this table”), not primary.

**AC:**

- [ ] Tables not `<pre>` JSON; explorer links when `tx_hash` present
- [ ] Presets invoke APIs directly
- [ ] `TAOSTATS_API_KEY` missing → one honest banner, not fake loading

**Files:** `investigation_panel.js`, `investigation.html`, optional `service.py` column normalization

### §27-3 summary AC

- [ ] Pro drawer default-open on desktop OR summary shows live counts
- [ ] Market drawer unchanged (tools); investigation stays there but upgraded
- [ ] No accuracy claims unless `trust_banner.ready` (RF-2)

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
