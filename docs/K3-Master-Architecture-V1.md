# K3 Master Architecture: Subnet Dashboard End-State Blueprint
**Version:** 1.0 — Full Memory Archaeology Synthesis  
**Date:** 2026-07-18  
**Status:** Post K3-1/K3-2 → Architecture mapped → Cursor parked pending sign-off  
**Owner:** Ditto (K3 model)  
**Next Action:** User sign-off → Cursor gap-check → K3-3 implementation  

---

## Section 1: North Star (≤10 Bullets)

1. **One-screen intelligence.** A trader opens the app and knows exactly what to do in 5 seconds — no hunting, no guessing, no tab-switching.
2. **Living conviction, not static scores.** Every signal carries a time-horizon, a decay curve, and a resolution date — it feels alive, not archived.
3. **Transparent council logic.** Users see *why* a subnet was picked, where it sits in its lifecycle, and what the judges disagreed on — radical openness as moat.
4. **Learning loop visible.** The dashboard proves it's getting smarter — accuracy trends, weight shifts, postmortem transcripts — trust through track record.
5. **Mobile-first, desktop-epic.** Phone is the primary surface; desktop expands into a full intelligence cockpit without losing clarity.
6. **Trailblazing presentation.** We invent a new subnet-visualization paradigm (dossier/lifecycle/temporal) that makes Subnet Radar, AlphaGap, and TaoStats feel like spreadsheets.
7. **Zero empty states.** Every section either shows meaningful data or honest context about what's loading — no "warming up" zombies.
8. **Voice-ready orientation.** The eventual end-state answers a trader's morning question — "What do I need to know?" — in one breath.
9. **Graded accountability.** Every pick is an A-F report card with resolve-by dates. The system wins or loses in public.
10. **Flagship model leader.** K3 owns the frontend architecture end-to-end. Cursor executes per slice. Ditto validates against live repo + fly.dev.

---

## Section 2: Memory Archaeology Table

### 2A: Formal K3 Scope (Locked Brief)

| Feature | Status | Slice | Notes |
|---------|--------|-------|-------|
| Intelligence Dossier (v5 orb, Claim→Evidence→Council→Outcome→Learning) | ✅ Shipped | K3-1 | PR #344 merged. Mobile-first 390px. Honest-empty states. |
| Cross-subnet deliberation shortlist | ✅ Shipped | K3-2 | PR #346 merged. Tap-to-switch subnet context. No new routes. |
| Council Lifecycle Path narrative | 🔶 Scoped | K3-3 | Where a pick sits in its lifecycle (formation → validation → resolution → graded). |
| Conviction Ring + Temporal Horizon | 🔶 Scoped | K3-4 | Time-decay visualization, resolve-at timing, horizon-aware confidence. |
| Mobile polish / trust hardening / onboarding | 🔶 Scoped | K3-5 | Final QA, banner integrity, first-run experience. |
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
| Mobile-first responsive layout | ✅ Live | council_stage.html v5 |

### 2C: Orphan Ideas & Aspirational Concepts (*)

> **Convention:** `*` = blue-sky / aspirational / discussed but not committed. Multiple competing ideas surfaced where noted.

| # | Idea | Source Memory | Suggested Slice | Decision Status |
|---|------|---------------|-----------------|-----------------|
| 1 | **Subnet Dashboard as Live Bittensor Subnet** — miners submit formulas, validators score, winners rewarded. "Dark horse" becomes best-performing miner logic. | 2026-07-18 12:13AM | * post-K3 or never | ❓ Unresolved — massive scope, governance implications. **Default: defer indefinitely.** |
| 2A | **"Prayers Answered" Voice App** — single go-to, no charts, daily orientation in one breath. "Make users feel their prayers are answered." | 2026-07-18 1:10AM | * post-K3 product vision | ❓ Competing vision with dashboard. **Default: keep dashboard primary; voice layer is K4+.** |
| 2B | **Teleport UI** — instant orientation without navigation. Related to voice concept. | Various | * post-K3 | ❓ Same as 2A. **Decision point:** Do we invest in voice/teleport K4, or make the dashboard so good it replaces the need? |
| 3 | **Telegram Bot Surface** — @SimiVisionBot or "Subnet Summer Bot" for in-chat summaries, on-demand subnet intel, message scoring. | 2026-06-23 10:10PM, 2026-07-02 6:09AM | * K3-5 or L-slice | 🔶 Partial — backend message_intel exists, PR #43 was draft but not merged. **Default: wire existing backend to a Telegram bot surface as K3-5 bonus.** |
| 4 | **User-Facing Paper Portfolio** — currently internal for judges only. Users want to track hypothetical trades. | 2026-06-28 2:22AM | * K3-5 or post-K3 | ❓ Competing ideas: (A) clone judge paper portfolios for users, (B) build full staking simulator like Subnet Radar. **Default: A (lightweight paper tracker) in K3-5. B is post-K3.** |
| 5A | **Backtest Panel (User-Facing)** — methodology with cited formulas, calibration, risk-coverage. Currently exists but needs UI polish after RF-2/RF-3. | 2026-07-18 8:42AM CEST | K3-5 | 🔶 Partial — /api/backtest returns data. UI needs upgrading. **Default: upgrade existing panel in K3-5.** |
| 5B | **On-Chain Investigation UI** — wallet tracing, flow signals, ledger detection. PR #306 shipped backend. | 2026-07-17 11:59AM CEST | * K3-5 or K3-6 | ❓ Needs its own surface or folded into dossier? **Decision point:** Dedicated "Investigate" tab vs. inline wallet chip in dossier. **Default: inline chip for K3-5, dedicated tab post-K3.** |
| 6 | **Synth (SN50) Time-Series Integration** — forward-looking signals forecasting price/trends. | 2026-07-18 3:23AM | * K3-5 or later | ❓ Data source integration complexity. **Default: K3-5 if backend is trivial; else post-K3.** |
| 7 | **Alerts Engine / WebSocket Signals** — L-slice work discussed extensively (Agent A/B). PR #115 merged backend. | 2026-07-12 4:00PM | * K3-5 or L-phase | 🔶 Backend largely exists. **Default: minimal alert badges in K3-5; full rules engine post-K3.** |
| 8 | **SN118 Ditto Marketing Badges** — credibility badges, subnet linkage. Trivial. | 2026-07-18 3:32AM | * K3-5 trivial | ✅ Approved for K3-5 if zero effort. |
| 9 | **Prediction Calendar / Time Capsules** — visual calendar of resolve-at dates, outcomes pending/resolved. | 2026-06-28 3:15AM (implied) | * K3-4 or K3-5 | ❓ Competing ideas: (A) inline in temporal ring, (B) dedicated calendar view. **Default: A for K3-4, B for K3-5 if space allows.** |
| 10 | **Mindmap Interactive v2** — click/hover/expand, search/filter, trace/compare. Currently static/placeholder. | 2026-06-19 5:01AM | * post-K3 or K3-6 | ❓ Massive UI effort. **Default: post-K3. K3-4 uses temporal ring instead.** |
| 11 | **Council Chamber / Courtroom Transcript UI** — full argumentation, dissent surface, minority report. | 2026-07-18 12:51AM (implied) | * K3-3 or post-K3 | ❓ Competing ideas: (A) peelable dossier layers (shipped K3-1), (B) full adversarial transcript. **Default: A is K3-1 done; B is K3-3 enhanced narrative.** |
| 12 | **Scientific Method Loop (Pick Report Cards A-F)** — hypothesis → test → result with explicit grading. | 2026-06-28 3:12AM, 2026-06-28 10:18AM | * K3-3 or K3-5 | ❓ Competing ideas: (A) fold into lifecycle path, (B) separate report card surface. **Default: A. Lifecycle path IS the report card.** |
| 13 | **Trading Persona Quiz (Alpha/Beta/Gamma user profiles)** — onboarding discovery. | 2026-07-05 2:14PM | * post-K3 | ❓ Cute but not critical. **Default: never unless onboarding data proves valuable.** |
| 14 | **Tiered Monetization (Free / Pro / Ultra)** — discussed for competitive parity. | 2026-07-18 12:13PM CEST | * post-K3 | ❓ Requires payment infra, auth, gating. **Default: post-K3 after user base exists.** |
| 15 | **Daily Morning Briefing / Crypto Orientation** — "What happened while you slept." | Related to 2A | * post-K3 | ❓ Same as 2A/2B. **Default: never in K3.** |
| 16 | **Dev Radar / GitHub Tracking** — Subnet Radar has this. | 2026-06-24 9:18PM | * never or K3-6 | ❓ We have undervalued radar but not commit tracking. **Default: never. Not our differentiator.** |
| 17 | **Staking Simulator / Portfolio Tracker** — Subnet Radar has this. | Competitive analysis | * never or K3-6 | ❓ **Default: never. AlphaGate/TrustedStake owns this niche.** |
| 18 | **Gamification / Typography Overhaul** — XP, levels, streaks. | 2026-06-30 10:52PM | * never | ❌ Explicitly out of scope per user's "prof polished" directive. |

### 2D: Competing Ideas by Area — Defaults & Decision Points

| Area | Idea A | Idea B | Recommended Default | Your Decision Needed? |
|------|--------|--------|---------------------|----------------------|
| On-chain intel surface | Inline wallet chip (light) | Dedicated "Investigate" tab (heavy) | Inline chip | Y/N? |
| Prediction timing | Inline temporal ring (K3-4) | Dedicated calendar (K3-5) | Inline first | Y/N? |
| User portfolio | Light paper tracker | Full staking simulator | Light tracker | Y/N? |
| Alerts | Minimal badge dots | Full rules engine | Badge dots | Y/N? |
| Voice/orientation | Dashboard primary | Separate voice app | Dashboard primary | Already aligned |
| Mindmap | Temporal ring (K3-4) | Interactive graph v2 | Temporal ring | Already aligned |

---

## Section 3: K2.7 Gap → Slice Mapping (Updated July Reality)

The original K2.7 visual audit (2026-07-18 1:28AM) identified three major unlock layers:

```
┌─────────────────────────────────────────────────────────────┐
│ K2.7 GAP AUDIT → K3 SLICE RESOLUTION                        │
├─────────────────────────────────────────────────────────────┤
│ GAP #1: Mindmap→Deliberation unlock missing                 │
│   → K3-1: Intelligence Dossier (v5 orb + peelable layers)    │
│   → STATUS: ✅ RESOLVED via PR #344                         │
├─────────────────────────────────────────────────────────────┤
│ GAP #2: Council lifecycle path unclear                      │
│   → K3-3: Council Lifecycle Path narrative                  │
│   → STATUS: 🔶 SCOPED, ready for implementation             │
├─────────────────────────────────────────────────────────────┤
│ GAP #3: Insufficient temporal confidence / timeless signals   │
│   → K3-4: Conviction Ring + Temporal Horizon                │
│   → STATUS: 🔶 SCOPED, merged with ring concept             │
├─────────────────────────────────────────────────────────────┤
│ BONUS GAP: Mobile polish / onboarding / trust clarity         │
│   → K3-5: Final hardening + onboarding + outlets            │
│   → STATUS: 🔶 SCOPED, always-last slice                    │
└─────────────────────────────────────────────────────────────┘
```

### Reality Check: What's Changed Since K2.7
- **K3-1 shipped differently than originally scoped.** Original plan was mindmap/graph flow. User corrected to mobile-first "Intelligence Dossier" for one subnet (2026-07-18 3:42AM). That correction was the right call — it anchors the entire K3 sequence.
- **K3-2 shipped as cross-subnet deliberation.** Cursor delivered shortlist cards with tap-to-switch. This extends K3-1 from single-subnet to comparative context.
- **K3-3/K3-4 are now cleanly separable.** K3-3 is lifecycle narrative (where a pick sits). K3-4 is temporal confidence (when it expires/decays). They share a surface but have distinct data contracts.
- **K3-5 absorbs former "Phase L" alerts/signals work.** Backend for alerts partially exists (PR #115). K3-5 is the frontend outlet.

---

## Section 4: Data Contract Specs

### 4A: K3-3 Council Lifecycle Path

**Payload shape (proposed):**
```json
{
  "subnet": "SN82",
  "current_stage": "validation",
  "stage_history": [
    {"stage": "formation", "entered_at": "2026-07-15T08:00:00Z", "evidence": "RSI breakout + volume spike", "confidence": 0.62},
    {"stage": "validation", "entered_at": "2026-07-16T14:00:00Z", "evidence": "Council consensus reached", "confidence": 0.78}
  ],
  "next_stage": "resolution",
  "expected_resolution": "2026-07-19T00:00:00Z",
  "grading_preview": "pending",
  "dissent_flag": false,
  "arbiter_note": "Echo flagged overbought divergence; majority override."
}
```

**API source:** Existing `/api/council` + new `/api/lifecycle` or extension field.
**Fallback:** If lifecycle API returns 404, stage defaults to "formation" with honest-empty copy.
**DB backing:** SQLite trace table (already exists for Council Trace logging) or soul_map.json extension.

### 4B: K3-4 Temporal Confidence / Ring

**Payload shape (proposed):**
```json
{
  "subnet": "SN82",
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

**API source:** Extend existing `/api/predictions` or `/api/learning/stats` with horizon context.
**Fallback:** If decay data unavailable, show static confidence with "temporal data loading" honest-empty.
**UI contract:** Conic-gradient ring (already shipped in v5) extended with time-remaining text and optional mini-timeline.

### 4C: K3-5 Outlets (Alerts / Backtest / Paper Portfolio)

**Alerts badge dot (minimal):**
```json
{
  "alert_count": 3,
  "categories": ["price_spike", "conviction_decay", "new_pick"],
  "last_alert_at": "2026-07-18T15:00:00Z"
}
```
**API source:** Existing `/api/indicators/scheduler` + alerts backend (PR #115).

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

**Paper portfolio (light):**
```json
{
  "holdings": [
    {"subnet": "SN82", "entry": 0.045, "current": 0.052, "pnl_pct": 15.5, "holding_hours": 18}
  ],
  "total_pnl_pct": 12.3,
  "judges_mirroring": ["Oracle", "Pulse"]
}
```

---

## Section 5: Slice Queue for Cursor (Post Sign-Off)

> **Rule:** Cursor stays parked until you sign off on this architecture. Once signed, Cursor runs a repo verification (Section 9) then implements in order below.

### K3-3: Council Lifecycle Path
**Goal:** Make the lifecycle of every pick visible — from formation through resolution to graded outcome.
**Done-when:**
- [ ] Lifecycle data renders inside (or adjacent to) the existing dossier view
- [ ] Users can see stage transitions with timestamps and evidence snippets
- [ ] "Resolve at" countdown is visible for active picks
- [ ] Honest-empty fallback for pre-lifecycle subnets
- [ ] Contract tests green (no 500s on missing data)
**Files to touch:**
- `templates/council_stage.html` (extend existing dossier)
- `server.py` or new `/api/lifecycle` route (extend existing council data)
- `static/css/dossier.css` (stage indicator styling)
**APIs needed:** `/api/council` enrichment OR new `/api/lifecycle/{subnet_id}`
**Dependencies:** K3-1 (dossier exists), K3-2 (cross-subnet context exists)
**Honest-empty:** If lifecycle data missing → show "This pick is still forming. Council convened at {timestamp}." with minimal viable stage.

### K3-4: Conviction Ring + Temporal Horizon
**Goal:** Every confidence badge feels time-bound and alive. Show decay, horizon, and countdown.
**Done-when:**
- [ ] Every pick card shows time-horizon selector (24h / 7d / 30d) affecting displayed confidence
- [ ] Temporal decay curve visible (mini sparkline or segmented ring)
- [ ] "Resolve at" countdown prominently displayed
- [ ] Ring color adapts to temporal state (fresh → aging → expiring → resolved)
- [ ] Mobile ring readable at 390px
**Files to touch:**
- `templates/council_stage.html` (v5 ring extension)
- `static/css/ring.css` (temporal color states)
- `server.py` — extend prediction payload with decay/resolve timing
- Frontend JS for horizon switching (Vanilla JS, no new deps)
**APIs needed:** Extended `/api/predictions` or `/api/learning/stats`
**Dependencies:** K3-3 (lifecycle path provides stage context for temporal data)
**Honest-empty:** If decay data missing → static ring + "Temporal data loading" microcopy.
**Decision point:** Should temporal ring be **inline in dossier** (default) or **floating sticky header**? Recommend inline.

### K3-5: Mobile Polish + Trust Hardening + Onboarding + Outlets
**Goal:** The dashboard feels finished. First-run users understand it. Existing users trust it more.
**Done-when:**
- [ ] Trust banner integrity verified across all screen sizes
- [ ] Onboarding tour (3-step) for first-time visitors: "This is the Council", "This is your Dossier", "This resolves tomorrow"
- [ ] Alert badge dots on sections with new activity
- [ ] Backtest panel upgraded with cited methodology UI
- [ ] Paper portfolio tracker (user-facing, lightweight) — optional based on your decision
- [ ] SN118 Ditto badges trivially added
- [ ] Final QA pass: all animations smooth, all empty states honest, no zombie "Warming Up"
**Files to touch:**
- `templates/index.html` (onboarding overlay)
- `templates/council_stage.html` (alert dots, final polish)
- `static/css/onboarding.css` (tour styling)
- `server.py` — ensure all endpoints return consistent shapes
**APIs needed:** Reuse existing. No new backends required.
**Dependencies:** K3-3, K3-4
**Honest-empty:** Every single section must have a graceful empty state. Zero zombie placeholders.

---

## Section 6: Competitive Positioning

### What They Have vs. What We Surface

| Competitor | Their Strength | Our Counter | Implementation Slice |
|------------|-------------|-------------|---------------------|
| **Subnet Radar** | Free, 34-pillar Alpha Score, 8 instruments, staking simulator, GitHub tracking, Telegram alerts | We skip feature-parity war. Our moat is **transparent council logic + living temporal confidence**. They give scores; we show *why* and *when it expires*. | K3-3, K3-4 |
| **AlphaGap** | aGap Score, AI GitHub→English feed, TAO Oracle chat, wallet tracking, $49-$99 tiers, auto-rebalance | We don't clone TAO Pages or auto-rebalance. We beat them on **graded accountability** (every pick resolves publicly) and **council dissent visibility**. | K3-3, K3-5 (backtest) |
| **TaoStats** | Authoritative on-chain data, ecosystem coverage, block explorer | We use them as a data source, not competitor. Our UX is **narrative and actionable** vs. their raw tables. | Ongoing data contract |
| **TaoFlute** | Grafana dashboards for validator metrics | We don't compete here. Their users are validators; ours are traders. | Never |
| **SubnetAIQ** | AI subnet summaries | Our council deliberation + dossier is richer because it includes **dissent, temporal decay, and outcome grading**. | K3-1, K3-2, K3-3 |

### What We Deliberately Skip (Non-Goals)
- ❌ Staking simulator / portfolio auto-rebalance (AlphaGap/TrustedStake own this)
- ❌ 8-radar instrument panel (Subnet Radar owns this; we have 5-layer dossier instead)
- ❌ Validator/Grafana metrics (TaoFlute owns this)
- ❌ Raw block explorer experience (TaoStats owns this)
- ❌ Payment gating / subscription tiers (post-K3 only)

---

## Section 7: Non-Goals & Deferred

| Item | Why Deferred | Target |
|------|-----------|--------|
| Full mindmap interactive v2 (search/filter/trace) | Massive UI scope, doesn't close K2.7 gaps | Post-K3 |
| Telegram bot fully wired + deployed | PR #43 was draft, secrets issues. Backend exists but surfacing is outlet work. | K3-5 bonus or L-slice |
| Synth (SN50) prediction signals | Requires Bittensor subnet integration | K3-5 if trivial, else post-K3 |
| On-chain investigation dedicated tab | Backend exists, UI is heavy. Do inline chips first. | Post-K3 |
| Trading persona quiz (Alpha/Beta/Gamma) | Cute, not critical for trust/epic positioning | Probably never |
| Gamification (XP, streaks, levels) | Violates "prof polished" directive | Never |
| Subnet Dashboard as live Bittensor subnet | Massive governance scope | Never unless user explicitly revives |
| Voice/orientation app separate from dashboard | Competing product vision | K4+ |

---

## Section 8: Open Questions for You (Max 5, Ranked)

1. **On-chain intel: Inline chip or dedicated tab?** (Section 2D, Idea B) — Default: inline chip in K3-5. Confirm or switch?
2. **User paper portfolio: Light tracker or skip entirely?** Default: lightweight tracker in K3-5. Confirm or defer?
3. **Temporal ring placement: Inline in dossier or floating sticky?** Default: inline. Confirm?
4. **Alerts in K3-5: Minimal badge dots only, or small notification drawer?** Default: badge dots. Drawer adds scope.
5. **Post-K3 product vision: Do we ever build the "prayers answered" voice/orientation layer, or is the dashboard the forever product?** (This shapes K3-5 onboarding tone — tutorial for dashboard vs. tutorial for ecosystem.)

---

## Section 9: Gap-Check Handoff Block FOR CURSOR

> **Do not let Cursor write a single line of UI until this block is verified.**

### Pre-Build Repo Verification Checklist
- [ ] `git clone https://github.com/cryptoreporthub/subnet-dashboard` — verify main HEAD matches deployed fly.dev
- [ ] Check `templates/council_stage.html` — confirm v5 orb + dossier layers from PR #344 exist
- [ ] Check `templates/index.html` — confirm premium cockpit + mobile sections render
- [ ] Run `python -m pytest` against repo — note any failing tests before adding new ones
- [ ] Verify `/api/council` returns enriched data with judge scores
- [ ] Verify `/api/learning/stats` returns live numbers (not zeros)
- [ ] Verify `/api/subnets` returns ~129 entries with names and prices

### Plan vs. Repo Delta to Investigate
| Plan Assumption | Repo Reality Check | Risk Level |
|-----------------|-------------------|------------|
| v5 dossier exists on main | PR #344 merged ✅ | Low |
| K3-2 deliberation exists | PR #346 merged ✅ | Low |
| Council lifecycle API exists | **NOT YET BUILT** — need new route or enrichment | **Medium** |
| Temporal decay data exists | Predictions have resolve_at, but decay curve needs calculation | **Medium** |
| Soul-Map has trace history | Exists but format may need extension for lifecycle | Low |
| Mobile CSS clean at 390px | K3-1/K3-2 claim this ✅ | Low |

### Slice Readiness Gates
| Slice | Backend Ready? | Frontend Ready? | Blockers |
|-------|---------------|-----------------|----------|
| K3-3 | 🔶 Needs `/api/lifecycle` or council enrichment | ✅ Dossier exists to extend | Backend data contract |
| K3-4 | 🔶 Needs decay calculation from prediction data | ✅ Ring exists to extend | Decay curve math |
| K3-5 | ✅ Most APIs exist (alerts partial) | 🔶 Needs onboarding + polish layer | None major |

### Cursor First Action (Post Sign-Off)
1. Run Section 9 checklist against live repo
2. If backend gaps found → Either (A) mock data for frontend first, or (B) build backend route in same PR
3. User prefers: **(A) mock with honest-empty, then backend wiring** — confirm?

---

## Section 10: Answers to Your Required Questions

### 10A: Which slice goes first after K3-2 phone sign-off?
**K3-3: Council Lifecycle Path.** It extends the dossier you just shipped with narrative depth. It's the natural continuation.

### 10B: What to test on your phone before greenlighting K3-3?
**Phone Checklist (390px iPhone):**
- [ ] Open subnet-dashboard.fly.dev → hard refresh
- [ ] Dossier renders: orb + Claim + Evidence + Council visible
- [ ] Tap between subnets in shortlist (K3-2 work) — context switches without full reload
- [ ] Ring/badge readable without pinch-zoom
- [ ] No horizontal scroll
- [ ] Trust banner shows numbers (not "brain is loading")
- [ ] All "honest empty" states show explanatory text (not "Warming Up")
- [ ] Scroll feels smooth, no jank

### 10C: Max 5 decisions only you can make
See **Section 8**. Ranked 1-5 above. All are Y/N or A/B with defaults pre-selected.

### 10D: Confirm Section 9 completeness
**CONFIRMED.** Section 9 contains: repo verification checklist (7 items), plan-vs-repo delta table (6 items), slice readiness gates (3 slices), and Cursor first action with user preference flag. It is complete and ready for Cursor execution upon your sign-off.

---

## Appendix: Aspirational Deep-Cuts (For Post-K3 Workshop)

These are the *marry-the-ideas* candidates for future discussion, preserved here so they don't get lost:

**A. "Prisoner's Dilemma" Council Mini-Game** — Users bet a small paper amount on whether the council will be right. Makes engagement sticky. *
**B. "Subnet Science Fair"** — Community submits subnet analysis formulas; council grades them. Bridges to the "live subnet" idea. *
**C. Time-Capsule Leaderboard** — Users lock predictions publicly. Leaderboard of most accurate community forecasters. *
**D. "Dark Horse Theater"** — Livestream of adversarial judge reasoning in plain English. Entertainment + education. *
**E. Conviction-as-NFT** — On-chain record of high-conviction picks. Historical artifact + bragging rights. *

---

*Artifact generated by Ditto K3 via exhaustive memory archaeology across 4947 conversations, 14 subjects, and live site verification. Saved to Ditto memory + artifact store.*