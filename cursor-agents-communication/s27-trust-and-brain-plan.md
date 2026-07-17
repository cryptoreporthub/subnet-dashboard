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
| **§27-3** | **Living Focus + Public Self-Update** | Focus · Contest · Prove it · **Watch us update** (trailblazer unlock) | No |
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

## §27-3 — Living Focus (Tier 3 true potential)

**Grok LOCK (2026-07-17):** CONDITIONAL on prior “unbury APIs into cards” plan — **reframed**.

### The unlock (not more sections)

Tier 3 is **one Focus Object** that the whole brain reorients around — not a Labs strip + peek + bench as three new dumps.

| Concept | Meaning |
|---------|---------|
| **Focus** | `data-focus-netuid` — defaults to daily-pick (`pick` ?? `candidate`); user can switch |
| **Alive beat** | Judge **contention** — Oracle/Echo/Pulse disagree (`consensus.contested` / low `agreement`) |
| **Prove it** | One-tap from focus → sellers table for that SN (investigation as evidence, not debug JSON) |
| **Memory** | Time-capsule CTA when focus has a graded call — don’t rebuild trail UI |

**ONE hero interaction:** Focus a netuid → watch three judges contest it → one-tap “Who sold SN{n}?” proves the call.

**Kill:** Labs 3-card strip. Fold scenario/regime, ruggers risk, latest autopsy into **≤3 chrome chips** on the bench (honest-empty).

**IA note:** Selectively reverses §17 U1 demotion for the *argument* layer only — hero stays single-job; Focus is “why this call / prove it,” not card sprawl.

### Cross-cutting: name + focus integrity

- Every name: `enrich_subnet_row` / `resolve_subnet_name` — **never hardcoded** subnet examples in templates/docs demos
- Focus default: `/api/daily-pick` → `pick.subnet.netuid` ?? `candidate.subnet.netuid`
- Shared state: one tiny `focus_netuid` helper in hydrate JS — bench, chrome chips, inv default, switcher all read it
- **Blocking:** fix `/api/simivision` `SNNone` / null names before Focus switcher ships
- Unresolved names show as `SN{n}` honestly

### NON-GOALS (protect focus)

- No Redis / new deps / Flask / league-table `/api/judges` on home
- No §28 shareable pages in this phase
- No Pro/Market redesign beyond demoting league judges off home hydrate
- No accuracy / win-rate copy outside `trust_banner` (RF-2) — contested = **disagreement**, not “we’re right”
- No fourth weight path (§27-4 owns nudge)

---

### §27-3a — Living Focus (merge prior 3a+3b)

**One PR.** Bench + contested drama + Focus switcher + chrome chips.

**Placement:** `#section-living-focus` after story-strip, before story-path.

**Hydrate (fast — never 50-subnet `/api/judges` on home):**

```
GET /api/daily-pick                 → default focus + audited vs candidate-only
GET /api/judges/{focus}             → oracle, echo, pulse, consensus (contested!)
GET /api/calibration/status         → weights; lean = who drives *this* call
GET /api/simivision                 → top 3 as Focus switcher (enriched names)
GET /api/ruggers/subnet/{focus}     → optional amber risk chip
GET /api/scenario-memory (summary)  → optional regime chip
GET /api/postmortems (newest 1)     → optional autopsy chip
```

**UI hierarchy (drama first):**

1. **Header** — Focus name · SN · LONG/HOLD · audited vs “candidate only”
2. **Contention** — three judges with scores; if `contested` or agreement low → highlight split (“Council split”)
3. **Who drives** — top expert lean from weights / expert_contributions; bars secondary
4. **Chrome chips** (≤3, honest-empty) — regime · rug risk on focus · latest miss
5. **Focus switcher** — tap SimiVision top-3 → reorient entire Living Focus without reload
6. **CTA row** — “Prove it: who sold SN{n}?” (scrolls/opens investigation with focus prefilled) · optional “Replay” time-capsule if graded

**Story path:** step 2 → `2 · Council experts`; optional 2b from `/api/judges/{focus}`.

**AC:**

- [ ] Focus SN = daily-pick default; switcher changes bench + chrome + inv default without reload
- [ ] Contested/agreement visible when judges disagree; scores match `/api/judges/{focus}` (±0.001)
- [ ] No Labs card strip — ≤3 chrome chips, honest-empty when APIs dark
- [ ] Switcher rows never show SNNone/null names
- [ ] League-table `/api/judges` demoted off home hydrate (`brain_bench.js` / focus helper only)
- [ ] RF-2: no win-rate/accuracy copy outside trust_banner

**Files:** `living_focus.html`, `living_focus.js` (or `focus_netuid` + `brain_bench.js`), `premium_cockpit.html`, `story_path.py`, `cockpit_hydrate.js`, simivision name enrichment, `council_first.css`

**Risk:** PR size — ship chrome chips thin; defer time-capsule CTA if needed.

---

### §27-3b — Prove it (investigation desk)

**Problem:** Best APIs render as `<pre>` JSON; presets only fill chat.

**Modes (focus-coupled):**

1. **Sellers table** — `GET /api/investigate/subnet/{focus}/sellers` (wallet, side, TAO, time, tx)
2. **Wallet trace** — `GET /api/investigate/wallet/{ss58}/flow`
3. **Presets → API** — `POST /api/investigate/ask`; owner-check from top sellers

Default netuid = Focus. Preset labels dynamic from Focus name. Chat explains the table — not primary.

**AC:**

- [ ] Tables + explorer links; not JSON dumps
- [ ] Living Focus “Prove it” CTA prefills + runs sellers for Focus SN
- [ ] Missing TaoStats → one honest banner
- [ ] RF-2 honored

**Files:** `investigation_panel.js`, `investigation.html`, optional `service.py` column normalize

---

### §27-3c — Public Self-Update (the trailblazer unlock)

**Grok LOCK (2026-07-17, second pass):** The moat beyond Living Focus.

**Name:** Public Self-Update  
**Fourth beat:** Focus → Contest → Prove it → **Watch us update**

TaoStats explores. Nansen labels. TradingView charts. Polymarket markets conviction.  
**None of them show a learning council that ate a miss (or banked a hit) and moved its weights in public.**

**Hero moment (~10s):** You land on Focus and see the last graded beat on this SN — RIGHT/WRONG → which expert moved → weight delta — then Replay/Share that confession.

**UI (thin — one Focus strip, not a trail rebuild):**

```
┌─ Last learn (Focus SN{n}) ────────────────────────────────────────┐
│  MISS · expected +2.1% → actual −1.4%                             │
│  technical 1.18 → 1.16 (−0.02) · weight_change from resolve       │
│  [Replay time capsule]  [Share graded call]                       │
└────────────────────────────────────────────────────────────────────┘
```

Honest-empty when Focus has no graded resolve: “No graded beat on this SN yet — appears after resolver tick.”

**APIs only (no new backends):**

| Need | Source |
|------|--------|
| Last grade on Focus | pick-history / predictions resolved by `focus_netuid`, or story-strip row |
| Expert nudge delta | `/api/mindmap/trail` `weight_change`, or postmortem |
| Current weights | `/api/calibration/status` |
| Replay / Share | `/api/predictions/capsule/{id}` + existing OG share |

**Sits on Living Focus:** same `focus_netuid`; switcher reloads learn beat; Prove it = evidence, Self-Update = accountability.

**§27-4 relationship:** 3c *surfaces* trail emits; `nudge_expert` hygiene stays in §27-4 — no fourth weight path.

**AC:**

- [ ] Focus with graded history shows last grade + expert nudge delta
- [ ] Before→after (or last nudge) matches trail + calibration (±ε)
- [ ] Replay + Share wire to existing time-capsule / OG share for that call
- [ ] Switch Focus clears/reloads learn beat; honest-empty when none
- [ ] RF-2: no win-rate copy outside `trust_banner`

**NON-GOALS:** Global accuracy theater · rebuilt trail/league UI · live WebSocket nudge spam · Redis · Labs strip revival · §28 pages

**Risks:** Prod resolver quiet → empty learn beat · scope creep into full trail rebuild

**Files:** extend Living Focus with Last-learn strip; reuse `time_capsule.js`; thin trail filter by focus

---

### §27-3 summary AC (true potential unlocked)

- [ ] User can Focus → see judge split → Prove it → sellers table in one continuous flow
- [ ] Switching Focus reorients bench + chips + inv default (no page reload)
- [ ] Contested council is the emotional beat — not score cells alone
- [ ] No Labs strip; no accuracy theater outside trust_banner
- [ ] **Public Self-Update:** Focus shows last grade → expert nudge → before/after → Replay/Share (honest-empty when none)

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
