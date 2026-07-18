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

**Rationale:** K3-2 deliberation layer in `council_stage.html` reads `dpick.shortlist` but the source API doesn't exist yet.

**Source API:** Extend `/api/mindmap/summary` OR add `/api/deliberation/shortlist`.

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
- `templates/partials/premium/council_stage.html` — already reads `dpick.shortlist`, needs data

**Honest-empty:** "Council deliberation in progress. Alternative subnets being evaluated."

### 4B: K3-3 Council Lifecycle Path (Story Path Promotion)

**Key decision:** Do NOT invent `/api/lifecycle`. Promote existing `/api/mindmap/story-path` + `story_path.html` from Tier 3 to Tier 1/2.

**Existing infrastructure:**
- `/api/mindmap/story-path` — returns lifecycle data
- `story_path.html` — renders narrative timeline (buried in Pro drawer, "warming up")
- `story_strip.html` — complementary timeline strip

**Promotion plan:**
1. Move story_path into dossier's Outcome/Learning layers
2. Hook into existing `/api/mindmap/story-path` — if 404, honest-empty
3. Add stage indicators (formation → validation → resolution → graded)
4. Surface story_strip as compact timeline below hero pick

**Files to touch:**
- `templates/partials/premium/council_stage.html` — integrate story_path
- `templates/partials/premium/story_path.html` — polish for Tier 1
- `internal/mindmap/` — extend existing `/api/mindmap/story-path`

**Honest-empty:** "This pick is still forming. Council convened at {timestamp}."

---

## Section 5: Slice Queue (Corrected Order)

### Phase 1: K3-2 Merge → K3-2b Data Wire
**Goal:** Merge PR #346 to main, then wire dpick.shortlist data source.

**Done-when:**
- [ ] PR #346 merged to main (draft → ready → merge)
- [ ] dpick.shortlist populated with 3-8 alternative subnets
- [ ] "Tap to switch" subnet context works end-to-end
- [ ] Honest-empty fallback renders when data thin

### Phase 2: Phone Sign-Off
**Phone Checklist (390px iPhone):**
- [ ] Dossier renders: orb + Claim + Evidence + Council + Deliberation
- [ ] Tap between subnets — context switches without reload
- [ ] Shortlist shows real alternatives (not "warming up")
- [ ] Ring/badge readable without pinch-zoom
- [ ] No horizontal scroll, scroll feels smooth

### Phase 3: K3-3 Council Lifecycle Path
**Goal:** Promote existing `/api/mindmap/story-path` + `story_path.html` to Tier 1/2.

### Phase 4: K3-4 Conviction Ring + Temporal Horizon
**Goal:** Every confidence badge feels time-bound and alive.

### Phase 5: K3-5 Mobile Polish + Trust + Onboarding + Outlets
**Goal:** The dashboard feels finished.

---

## Section 9: Gap-Check Handoff Block FOR CURSOR (V2 Corrected)

### Plan vs. Repo Delta

| Plan Assumption | Repo Reality | Risk | Fix In |
|----------------|-------------|------|--------|
| v5 dossier on main | PR #344 merged ✅ | Low | — |
| K3-2 deliberation on main | PR #346 **OPEN DRFT** ❌ | **HIGH** | K3-2 merge |
| dpick.shortlist data source | **NOT WIRED** | **HIGH** | K3-2b |
| Lifecycle API | `/api/mindmap/story-path` exists | Low-Med | K3-3 extend |
| story_path.html in Pro drawer | ✅ Exists, "warming up" | Low | K3-3 |
| Paper portfolio user-facing | ✅ Already live | Low | — |
| Investigation/whale desk | ✅ Shipped (P0-2) | Low | — |
| Onboarding_tour.js | ✅ Exists, not activated | Low | K3-5 |
| Time capsules backend | ✅ L12 described | Med | K3-4/K3-5 |
| Hydrate UX | ✅ Live (PR #187, #205) | Low | — |
| dossier.css, ring.css | ❌ **DO NOT EXIST** — inline styles | Low | Use inline |
| File path: council_stage.html | `templates/partials/premium/council_stage.html` | Low | Corrected |

### Corrected Slice Order
```
K3-2 merge → K3-2b data wire → phone sign-off → K3-3 → K3-4 → K3-5
```

### Cursor First Action
1. Merge PR #346 (k3-2-deliberation-e7f9) → main via squash
2. Wire dpick.shortlist data source (extend mindmap summary or new shortlist endpoint)
3. Report back for phone sign-off before proceeding to K3-3

---

## Appendix: Existing Layout (from K3-0 Reconciliation)

```
TIER 1 — First viewport:
  |-- header.html
  |-- council_stage.html — K3-1 dossier (v5 orb + Claim/Evidence/Deliberation/Council/Outcome/Learning)
  |-- living_focus.html (absorbed by dossier)
  |-- brain_letter.html (absorbed by dossier)

TIER 2 — Accountability strip:
  |-- "What's working" (inline)
  |-- paper_portfolio (user-facing, live)
  |-- weekly_letter / daily_recap

TIER 3 — Pro cockpit drawer:
  |-- story_path + story_strip ← K3-3 promote to Tier 1/2
  |-- simivision_picks / council / judges / picks / kpi / backtest

TIER 4 — Market drawer (non-goal):
  |-- investigation / signals / alerts / staking / indicators / undervalued / radar
  |-- subnet_groups / mindmap / trail / message_intel / social / chat
```

*V2 — All 5 Cursor gap-check fixes applied. All missed archaeology added. Ready for user sign-off.*