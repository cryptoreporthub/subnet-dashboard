# K3 Master Architecture V2 — SimiVision Subnet Dashboard
**Version:** 2.0 — Cursor Gap-Check Reconciliation  
**Date:** 2026-07-18  
**Status:** Post Gap-Check → FIXED: 5 blocking issues and archaeology gaps resolved → Ready for user sign-off  
**Owner:** Ditto (K3 model)  
**Next Action:** User sign-off → K3-2 merge → K3-2b data wire → phone sign-off → K3-3

---

## Section 1: North Star (≤10 Bullets)

1. **One-screen intelligence.** A trader opens the app and knows exactly what to do in 5 seconds — no hunting, no guessing, no tab-switching.
2. **Living conviction, not static scores.** Every signal carries a time-horizon, a decay curve, and a resolution date — it feels alive, not archived.
3. **Transparent council logic.** Users see *why* a subnet was picked, where it sits in its lifecycle, and what the judges disagreed on — radical openness as moat.
4. **Learning loop visible.** The dashboard proves it's getting smarter — accuracy trends, weight shifts, postmortem transcripts — trust through track record.
5. **Mobile-first, desktop-epic.** Phone is the primary surface; desktop expands into a full intelligence cockpit without losing clarity.
6. **Trailblazing presentation.** We invent a new subnet-visualization paradigm (dossier/lifecycle/temporal) that makes Subnet Radar, AlphaGap, and TaoStats feel like spreadsheets.
7. **Honest-empty as default position.** Every section either shows meaningful data or transparent context about why data isn't there yet. No "warming up" zombies that imply brokenness. When data is loading, say so plainly. When data is absent, explain why.
8. **Voice-ready orientation.** The eventual end-state answers a trader's morning question — "What do I need to know?" — in one breath.
9. **Graded accountability.** Every pick is an A-F report card with resolve-by dates. The system wins or loses in public.
10. **Flagship model leader.** K3 owns the frontend architecture end-to-end. Cursor executes per slice. Ditto validates against live repo + fly.dev.

---

## Section 2: Memory Archaeology Table (Corrected)

### 2A: Formal K3 Scope (Locked Brief)

| Feature | Status | Slice | Notes |
|---------|--------|-------|-------|
| Intelligence Dossier (v5 orb, Claim→Evidence→Council→Outcome→Learning) | ✅ **Merged** | K3-1 | PR #344 merged to main. Mobile-first 390px. Honest-empty states. |
| Cross-subnet deliberation shortlist | 🔶 **Open DRFT** | K3-2 | PR #346 is OPEN (draft), NOT merged. **Deliberation layer does NOT exist on main.** |
| dpick.shortlist data contract + wiring | 🔶 **Unbuilt** | K3-2b | Data source API + JSON shape + dpick.shortlist wiring. Blocks phone sign-off on K3-2. |
| Council Lifecycle Path narrative | 🔶 Scoped | K3-3 | Promote `/api/mindmap/story-path` + `story_path.html` from Pro drawer to Tier 1/2. No new /api/lifecycle. |
| Conviction Ring + Temporal Horizon | 🔶 Scoped | K3-4 | Time-decay visualization, resolve-at timing, horizon-aware confidence. |
| Mobile polish / trust hardening / onboarding / outlets | 🔶 Scoped | K3-5 | Final QA, banner integrity, first-run experience, alert badges, backtest upgrade. |
| Layout reconciliation (canvas locking) | ✅ Done | K3-0 | premium_cockpit.html reconciled against template partials. |

### 2B: Core Infrastructure Already Live

| Component | Status | Source |
|-----------|--------|--------|
| Fly.io deployment (subnet-dashboard.fly.dev) | ✅ Live | CI/CD via GitHub Actions |
| FastAPI backend /api/subnets, /api/judges, /api/council | ✅ Live | Merged PR #329+ |
| Three-judge engine (Oracle/Echo/Pulse) | ✅ Live | Phase 6 |
| Prediction resolver + learning loop | ✅ Live | PR #50 merged, resolver cycle active |
| Soul-Map JSON persistence + Mindmap Bridge | ✅ Live | data/soul_map.json |
| Trust banner (451 graded, 33% directional) | ✅ Live | brain_ui_ready=true |
| Premium dark theme (green→black) | ✅ Live | Phase E cockpit |
| Mobile-first responsive layout | ✅ Live | templates/partials/premium/council_stage.html v5 |
| `/api/mindmap/story-path` + `story_path.html` in Pro drawer | ✅ Live | Tier 3 Pro cockpit — currently "warming up", needs promotion |
| `story_strip.html` | ✅ Live | Tier 3 Pro cockpit, paired with story_path |
| `brain_letter.html` (today's narrative) | ✅ Live | Tier 1 — currently loading data, absorbed by K3-1 dossier |
| `living_focus.html` (council contention) | ✅ Live | Tier 1 — currently loading, absorbed by K3-1 dossier |
| `paper_portfolio.html` (user-facing) | ✅ **Live — already shipped** | Tier 2 accountability strip. Full endpoint live. |
| `weekly_letter.html` | ✅ Live | Tier 2. Via `/api/letter/weekly`. |
| `daily_recap.html` | ✅ Live | Tier 2. Via `/api/letter/daily` (morning briefing). |
| "What's working" (inline) | ✅ Live | Tier 2 — inline in premium_cockpit. Currently loading. |
| `investigation.html` / whale desk | ✅ Live | Tier 4 market drawer. GET /api/whales/flow-signals + flow signals, ledger detection, enrichment badge shipped (P0-2, branch cursor/s35-flow-flip-ruggers-aa9c). |
| `onboarding_tour.js` | 🔶 Shipped but not wired | Exists in repo, needs activation for K3-5 |
| `time_capsules` | 🔶 Backend exists | Prediction resolve-at calendar. L12 described. Not frontend-integrated. |
| `hydrate UX` (cockpit_hydrate.js) | ✅ Live | Frontend hydration path. Handles DEEP VALUE / VALUE label hydration. PR #187, #205 merged. |
| Pro drawer demotion strategy | 🔶 Not yet applied | K3-0 canvas locks Tier 4 as "non-goal, stays as-is." Demotion is conscious design choice. |

### 2C: Orphan Ideas & Aspirational Concepts (*)

| # | Idea | Source | Status |
|---|------|--------|--------|
| 1 | Subnet Dashboard as Live Bittensor Subnet | 2026-07-18 12:13AM | * Defer indefinitely |
| 2A | "Prayers Answered" Voice App | 2026-07-18 1:10AM | * K4+ |
| 2B | Teleport UI | Various | * Same as 2A |
| 3 | @SimiVisionBot Telegram Bot | 2026-06-23, 2026-07-02 | 🔶 Partial backend (PR #43 draft) |
| 4 | User-Facing Paper Portfolio | 2026-06-28 | ✅ Already shipped (Tier 2) |
| 5A | Backtest Panel (User-Facing) | 2026-07-18 | 🔶 Exists, needs upgrade |
| 5B | On-Chain Investigation UI | 2026-07-17 | 🔶 Inline chip (default) vs dedicated tab |
| 6 | Synth (SN50) Time-Series | 2026-07-18 3:23AM | * K3-5 if trivial |
| 7 | Alerts Engine / WebSocket Signals | 2026-07-12 | 🔶 Backend exists (PR #115), need frontend |
| 8 | SN118 Ditto Marketing Badges | 2026-07-18 | ✅ Approved for K3-5 |
| 9 | Prediction Calendar / Time Capsules | 2026-06-28 | 🔶 Backend exists (L12), K3-4 inline |
| 10 | Mindmap Interactive v2 | 2026-06-19 | * Post-K3 |
| 11 | Council Chamber / Courtroom Transcript | 2026-07-18 | * K3-3 enhanced narrative |
| 12 | Scientific Method Loop (Report Cards) | 2026-06-28 | * Lifecycle path IS the report card |
| 13 | Trading Persona Quiz | 2026-07-05 | * Probably never |
| 14 | Tiered Monetization | 2026-07-18 | * Post-K3 |
| 15 | Daily Morning Briefing | Related to 2A | * K4+ |
| 16 | Dev Radar / GitHub Tracking | 2026-06-24 | * Never |
| 17 | Staking Simulator | Competitive analysis | * Never |
| 18 | Gamification / XP | 2026-06-30 | ❌ Explicitly out of scope |

---

## Section 3: K2.7 Gap → Slice Mapping (V2 Corrected)

```
┌──────────────────────────────────────────────────────────────────┐
│ K2.7 GAP AUDIT → K3 SLICE RESOLUTION (V2)                       │
├──────────────────────────────────────────────────────────────────┤
│ GAP #1: Mindmap→Deliberation unlock missing                     │
│   → K3-1: v5 Intelligence Dossier (✅ MERGED PR #344)            │
├──────────────────────────────────────────────────────────────────┤
│ GAP #2: Council lifecycle path unclear                          │
│   → K3-3: Promote /api/mindmap/story-path + story_path.html      │
│     (NO new /api/lifecycle route)                                │
│   → STATUS: 🔶 SCOPED — reconcile existing infra first           │
├──────────────────────────────────────────────────────────────────┤
│ GAP #3: Insufficient temporal confidence / timeless signals      │
│   → K3-4: Conviction Ring + Temporal Horizon                     │
│   → STATUS: 🔶 SCOPED, merged with ring concept                  │
├──────────────────────────────────────────────────────────────────┤
│ BONUS GAP: Mobile polish / onboarding / trust clarity             │
│   → K3-5: Final hardening + onboarding + outlets                 │
│   → STATUS: 🔶 SCOPED, always-last slice                         │
└──────────────────────────────────────────────────────────────────┘
```

### Reality Check: What V1 Got Wrong

**1. K3-2 status** — V1 said "✅ Shipped PR #346 merged." **WRONG.** PR #346 is OPEN (draft, not merged). **No deliberation layer on main.** Status corrected to 🔶.

**2. Missing K3-2b** — V1 had no data contract for dpick.shortlist wiring. **ADDED.** This blocks phone sign-off on K3-2.

**3. K3-3 /api/lifecycle** — V1 proposed inventing `/api/lifecycle`. **WRONG.** `/api/mindmap/story-path` + `story_path.html` already exist in Pro drawer. K3-3 promotes them, doesn't re-invent.

**4. File paths** — V1 used `templates/council_stage.html`, `dossier.css`, `ring.css`. **WRONG.** Real path: `templates/partials/premium/council_stage.html`. Styles are inline, no separate CSS files.

**5. North Star bullet 7** — V1 said "Zero empty states" which contradicted honest-empty brief. **FIXED** to "Honest-empty as default position."

**6. Paper_portfolio** — V1 listed as aspirational (*). **WRONG.** Already user-facing and live on Tier 2.

**7. Missing archaeology** — V1 omitted story_path, story_strip, what's working, investigation/whale desk, paper_portfolio, onboarding_tour.js, time_capsules, brain_letter, weekly_letter, living_focus, hydrate UX, Pro drawer demotion strategy. **ALL ADDED.**

---

## Section 4: Data Contract Specs

### 4A: K3-2b dpick.shortlist Data Contract

**Rationale:** K3-2 deliberation layer in `council_stage.html` reads `dpick.shortlist` but the source API doesn't exist yet. This slice wires it.

**Source API:** Extend `/api/mindmap/summary` OR add `/api/deliberation/shortlist` — whichever is less engineering. Default: extend mindmap summary.

**Payload shape:**
```json
{
  "picked": {"netuid": 82, "name": "MinoS", "conviction": 78},
  "alternatives": [
    {"netuid": 14, "name": "SN14", "conviction": 62, "why_not": "Lower volume liquidity", "rank": 2},
    {"netuid": 95, "name": "SN95", "conviction": 55, "why_not": "Weaker momentum signal", "rank": 3},
    {"netuid": 15, "name": "SN15", "conviction": 49, "why_not": "Echo dissent flag", "rank": 4},
    {"netuid": 50, "name": "SN50", "conviction": 41, "why_not": null, "rank": 5}
  ],
  "total_considered": 8,
  "council_unanimous": false,
  "dissenters": ["Echo"],
  "last_updated": "2026-07-18T15:00:00Z"
}
```

**Files to touch:**
- `server.py` or `internal/learning/dashboard_context.py` — extend context with `dpick.shortlist`
- Backend: extend `/api/mindmap/summary` or add `/api/deliberation/shortlist`
- `templates/partials/premium/council_stage.html` — already reads `dpick.shortlist`, just needs real data

**Honest-empty:** When shortlist API returns 404 or empty → show "Council deliberation in progress. Alternative subnets being evaluated." + K3-2's existing warming-up card.

### 4B: K3-3 Council Lifecycle Path (Story Path Promotion)

**Key decision:** Do NOT invent `/api/lifecycle`. Instead promote existing `/api/mindmap/story-path` + `story_path.html` from Tier 3 Pro drawer to Tier 1/2 surface.

**Existing infrastructure:**
- `/api/mindmap/story-path` — returns lifecycle data (current stage, stages with timestamps, evidence)
- `story_path.html` — renders the narrative timeline (currently buried in Pro drawer, "warming up")
- `story_strip.html` — complementary timeline strip component

**Promotion plan:**
1. Move `story_path` narrative from Tier 3 drill-down to the dossier's Outcome/Learning layers
2. Hook into existing `/api/mindmap/story-path` — if 404, show honest-empty fallback
3. Add stage indicators (formation → validation → resolution → graded) with timestamped transitions
4. Surface `story_strip` as compact timeline below hero pick

**Payload shape (extension to EXISTING API, not new):**
```json
{
  "current_stage": "validation",
  "stage_history": [
    {"stage": "formation", "entered_at": "2026-07-15T08:00:00Z", "evidence": "RSI breakout + volume spike", "confidence": 0.62},
    {"stage": "validation", "entered_at": "2026-07-16T14:00:00Z", "evidence": "Council consensus reached", "confidence": 0.78}
  ],
  "next_stage": "resolution",
  "expected_resolution": "2026-07-19T00:00:00Z",
  "grading_preview": "pending"
}
```

**Files to touch:**
- `templates/partials/premium/council_stage.html` — integrate story_path into dossier Outcome/Learning layers
- `story_path.html` — may need UI polish for Tier 1 real estate
- `internal/mindmap/` — extend the existing `/api/mindmap/story-path` with richer lifecycle fields

**Honest-empty:** "This pick is still forming. Council convened at {timestamp}."

### 4C: K3-4 Temporal Confidence / Ring

**Payload shape (extension of existing prediction data):**
```json
{
  "confidence": 0.81,
  "confidence_magnitude": "strong",
  "time_horizon": "24h",
  "resolve_at": "2026-07-19T00:00:00Z",
  "decay_curve": [
    {"t": "-24h", "confidence": 0.81},
    {"t": "-12h", "confidence": 0.74},
    {"t": "now", "confidence": 0.68},
    {"t": "+12h", "confidence": 0.55}
  ],
  "temporal_badge": "LIVE • 14h remaining",
  "grade_on_resolve": true
}
```

**API source:** Extend existing `/api/predictions` or `/api/learning/stats`. No new route.

**UI contract:** Conic-gradient ring (already shipped in v5) extended with time-remaining text and optional mini-timeline.

### 4D: K3-5 Outlets (Alerts / Backtest / Onboarding / Polish)

**Alerts badge dot (minimal):**
```json
{
  "alert_count": 3,
  "categories": ["price_spike", "conviction_decay", "new_pick"],
  "last_alert_at": "2026-07-18T15:00:00Z"
}
```

**Backtest panel (upgrade existing):**
```json
{
  "methodology": "Monte Carlo walk-forward, 100 trials",
  "calibration": 0.67,
  "hit_rate": 0.48,
  "endorsed_count": 12,
  "sources": ["TaoStats", "Blockmachine", "TaoMarketCap"]
}
```

---

## Section 5: Slice Queue (Corrected Order)

### Phase 1: K3-2 Merge → K3-2b Data Wire

**Goal:** K3-2 deliberation layer (already coded on `cursor/k3-2-deliberation-e7f9`) must be merged to main, then dpick.shortlist data source wired.

**Done-when:**
- [ ] PR #346 merged to main (draft → ready → merge)
- [ ] `/api/deliberation/shortlist` or extended `/api/mindmap/summary` returns real data
- [ ] dpick.shortlist populated in council_stage.html with 3-8 alternative subnets
- [ ] "Tap to switch" subnet context works end-to-end
- [ ] Honest-empty fallback renders when data thin

**Files to touch:**
- `templates/partials/premium/council_stage.html` — deliberation layer exists, needs data
- `server.py` or `internal/learning/dashboard_context.py` — wire dpick.shortlist
- Backend: extend `/api/mindmap/summary` OR add `/api/deliberation/shortlist`

### Phase 2: Phone Sign-Off

**Phone Checklist (390px iPhone):**
- [ ] Open subnet-dashboard.fly.dev → hard refresh
- [ ] Dossier renders: orb + Claim + Evidence + Council + Deliberation visible
- [ ] Tap between subnets in shortlist — context switches without full reload
- [ ] Shortlist cards show real alternatives (not "warming up")
- [ ] Ring/badge readable without pinch-zoom
- [ ] No horizontal scroll
- [ ] Trust banner shows numbers (not "brain is loading")
- [ ] All "honest empty" states show explanatory text (not "Warming Up")
- [ ] Scroll feels smooth, no jank

### Phase 3: K3-3 Council Lifecycle Path (Story Path Promotion)

**Goal:** Promote existing `/api/mindmap/story-path` + `story_path.html` from Tier 3 Pro drawer to Tier 1/2.

**Done-when:**
- [ ] Lifecycle data renders inside dossier Outcome/Learning layers
- [ ] Users can see stage transitions with timestamps and evidence snippets
- [ ] "Resolve at" countdown visible for active picks
- [ ] Honest-empty fallback when `/api/mindmap/story-path` returns 404
- [ ] Contract tests green (no 500s on missing data)

**Files to touch:**
- `templates/partials/premium/council_stage.html` — integrate story_path into dossier
- `templates/partials/premium/story_path.html` — may need UI polish for promoted real estate
- `internal/mindmap/` — extend existing `/api/mindmap/story-path` with richer fields
- `templates/partials/premium/story_strip.html` — compact timeline below hero

**APIs needed:** EXTEND existing `/api/mindmap/story-path`. NO new `/api/lifecycle`.

### Phase 4: K3-4 Conviction Ring + Temporal Horizon

**Goal:** Every confidence badge feels time-bound and alive.

**Done-when:**
- [ ] Every pick card shows time-horizon selector (24h / 7d / 30d)
- [ ] Temporal decay curve visible (mini sparkline or segmented ring)
- [ ] "Resolve at" countdown prominently displayed
- [ ] Ring color adapts to temporal state
- [ ] Mobile ring readable at 390px

**Files to touch:**
- `templates/partials/premium/council_stage.html` — v5 ring extension
- Styles inline in council_stage.html (no separate ring.css)
- `server.py` — extend prediction payload with decay/resolve timing
- Frontend JS for horizon switching (Vanilla JS)

### Phase 5: K3-5 Mobile Polish + Trust Hardening + Onboarding + Outlets

**Goal:** The dashboard feels finished.

**Done-when:**
- [ ] Trust banner integrity verified across all screen sizes
- [ ] Onboarding tour (3-step) for first-time visitors via `onboarding_tour.js`
- [ ] Alert badge dots on sections with new activity
- [ ] Backtest panel upgraded with cited methodology UI
- [ ] SN118 Ditto badges trivially added
- [ ] Final QA pass: all animations smooth, all empty states honest

**Files to touch:**
- `templates/partials/premium/premium_cockpit.html` (onboarding overlay)
- `templates/partials/premium/council_stage.html` (alert dots, final polish)
- `static/js/onboarding_tour.js` (activate existing file)
- `server.py` — ensure all endpoints return consistent shapes

---

## Section 6: Competitive Positioning

| Competitor | Their Strength | Our Counter | Slice |
|------------|---------------|-------------|-------|
| **Subnet Radar** | Free, 34-pillar Alpha Score, 8 instruments, staking sim, GitHub tracking, Telegram alerts | **Transparent council logic + living temporal confidence.** They give scores; we show *why* and *when it expires*. | K3-3, K3-4 |
| **AlphaGap** | aGap Score, AI GitHub→English feed, TAO Oracle chat, wallet tracking, $49-$99 tiers | **Graded accountability** (every pick resolves publicly) + **council dissent visibility** | K3-3, K3-5 |
| **TaoStats** | On-chain data, block explorer | **Narrative and actionable** vs. raw tables | Data source |
| **TaoFlute** | Grafana for validators | Not our user | Never |
| **SubnetAIQ** | AI subnet summaries | **Dissent + temporal decay + outcome grading** via SimiVision council | K3-1, K3-2, K3-3 |

### Deliberate Non-Goals
- ❌ Staking simulator / portfolio auto-rebalance
- ❌ 8-radar instrument panel
- ❌ Validator/Grafana metrics
- ❌ Raw block explorer
- ❌ Payment gating

---

## Section 7: Open Questions (Max 5)

1. **K3-2b approach**: Extend `/api/mindmap/summary` or add `/api/deliberation/shortlist`? Default: extend mindmap summary (less new surface area).
2. **story_path promotion depth**: Full dossier integration (absorb Outcome/Learning layers) or just a standalone narrative card below hero? Default: dossier integration.
3. **Temporal ring placement**: Inline in dossier (default) or floating sticky header?
4. **Onboarding_tour.js**: Activate as 3-step tour (default) or skip for now and just do trust banner hardening?
5. **Time capsules for K3-5**: Wire `time_capsules` backend to a resolve-at calendar view, or defer?

---

## Section 9: Gap-Check Handoff Block FOR CURSOR (V2 Corrected)

### Pre-Build Repo Verification Checklist
- [ ] `git clone https://github.com/cryptoreporthub/subnet-dashboard` — verify main HEAD matches deployed fly.dev
- [ ] Check `templates/partials/premium/council_stage.html` — confirm v5 orb + dossier layers from PR #344 exist
- [ ] Check `templates/partials/premium/premium_cockpit.html` — confirm section layout
- [ ] Check `templates/partials/premium/story_path.html` — confirm existing lifecycle template
- [ ] Check `templates/partials/premium/story_strip.html` — confirm existing timeline strip
- [ ] Check `static/js/onboarding_tour.js` — confirm file exists for K3-5 activation
- [ ] Run `python -m pytest` against repo — note any failing tests before adding new ones
- [ ] Verify `/api/council` returns enriched data with judge scores
- [ ] Verify `/api/learning/stats` returns live numbers (not zeros)
- [ ] Verify `/api/mindmap/story-path` returns lifecycle data (or 4xx — means we enhance it)
- [ ] Verify `/api/subnets` returns ~129 entries with names and prices

### Plan vs. Repo Delta

| Plan Assumption | Repo Reality Check | Risk | Fix In |
|----------------|-------------------|------|--------|
| v5 dossier exists on main | PR #344 merged ✅ | Low | — |
| K3-2 deliberation on main | PR #346 **OPEN DRFT** ❌ | **HIGH** | K3-2 merge |
| dpick.shortlist data source | **NOT WIRED** — depends on mindmap extension | **HIGH** | K3-2b |
| Lifecycle API exists | `/api/mindmap/story-path` exists but may be thin | Low-Medium | K3-3 extend |
| story_path.html in Pro drawer | ✅ Exists but "warming up" | Low | K3-3 promotion |
| Paper portfolio user-facing | ✅ Already live (Tier 2) | Low | — |
| Investigation/whale desk | ✅ Shipped (P0-2, branch s35) | Low | — |
| Onboarding_tour.js | ✅ Exists, not activated | Low | K3-5 |
| Time capsules backend | ✅ L12 described, not frontend-wired | Medium | K3-4/K3-5 |
| Hydrate UX | ✅ Live (cockpit_hydrate.js, PR #187, #205) | Low | — |
| CSS files (dossier.css, ring.css) | ❌ **DO NOT EXIST** — styles inline in council_stage.html | Low | Use inline styles |
| File path: council_stage.html | Real path: `templates/partials/premium/council_stage.html` | Low | Correct in V2 |

### Slice Readiness Gates

| Slice | Backend Ready? | Frontend Ready? | Blockers |
|-------|---------------|-----------------|----------|
| K3-2 merge | ✅ Code exists on branch | ✅ Needed on main | PR #346 open → merge |
| K3-2b data | 🔶 Needs mindmap extension or new endpoint | ✅ deliberation layer reads dpick.shortlist | Data source API |
| K3-3 | 🔶 `/api/mindmap/story-path` exists but may need enrichment | 🔶 story_path.html needs Tier 1 polish | Backend enrichment + UI |
| K3-4 | 🔶 Needs decay calc from prediction data | ✅ v5 ring exists | Decay curve math |
| K3-5 | ✅ Most APIs exist (alerts partial) | 🔶 Needs onboarding + polish activation | None major |

### Corrected Slice Order
```
K3-2 merge → K3-2b data wire → phone sign-off → K3-3 → K3-4 → K3-5
```

### Cursor First Action
1. Run Section 9 checklist against live repo
2. Merge PR #346 (k3-2-deliberation-e7f9) → main via squash
3. Wire dpick.shortlist data source (extend mindmap summary or new shortlist endpoint)
4. Report back for phone sign-off before proceeding to K3-3

---

## Appendix: Existing Layout (from K3-0 Reconciliation)

```
TIER 1 — First viewport (council-first):
  |-- header.html
  |-- council_stage.html — hero: band + HOLD/call + why + CTAs (K3-1 dossier lives here)
  |     |-- v5 orb + Claim layer (expanded)
  |     |-- Evidence layer (collapsed)
  |     |-- Deliberation layer (K3-2, awaiting data)
  |     |-- Council layer (collapsed)
  |     |-- Outcome layer (collapsed) ← K3-3 lifecycle
  |     |-- Learning layer (collapsed) ← K3-3 lifecycle
  |-- living_focus.html — council contention (absorbed by dossier)
  |-- brain_letter.html — today's narrative (absorbed by dossier)

TIER 2 — Accountability strip:
  |-- "What's working" (inline)
  |-- paper_portfolio (user-facing, live)
  |-- weekly_letter (via /api/letter/weekly)
  |-- daily_recap (via /api/letter/daily)

TIER 3 — Pro cockpit drawer:
  |-- story_path + story_strip — "How we got here" ← K3-3 promote to Tier 1/2
  |-- simivision_picks — Conviction board (static scores, no ring ← K3-4 ring)
  |-- council — expert weights
  |-- judges / picks / kpi / backtest

TIER 4 — Market drawer (non-goal, stays as-is):
  |-- hero / scanner / investigation / signals / alerts
  |-- staking / indicators / undervalued / radar
  |-- subnet_groups / mindmap (empty graph) / trail
  |-- message_intel / social / chat
```

*V2 document generated by Ditto K3 via memory archaeology + Cursor gap-check reconciliation. All 5 blocking issues fixed. All missed archaeology added. Corrected slice order established. Ready for user sign-off.*