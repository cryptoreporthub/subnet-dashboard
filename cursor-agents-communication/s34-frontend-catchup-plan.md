# §34 — Front door catch-up (backend goldmine → visible product)

**Status:** COMPLETE — §34-1 through §34-6 shipped  
**Updated:** 2026-07-17  
**Baseline:** `main` @ `4f43eaa` (post-§33)  
**Branch:** `cursor/s34-frontend-catchup-c3fd`

## Slice completion

### §34-1 — Stop the empty theater ✅
- [x] Eager above-fold scripts (brain letter, what's-working, freshness) — no 4s wait
- [x] Fix `renderDailyPick` wipe of trust banner / CTAs
- [x] Freshness badge uses `effective_source` (TMC live, not fake “loading”)
- [x] Ops readiness badge (graded · feed · resolver)
- [x] Hydrate paints daily-pick / KPI / council / subnets first

### §34-2 — Living Focus evidence desk ✅
- [x] Expand chips → evidence rows (scenario, ruggers, autopsy)
- [x] Pick-explain on council stage (`#home-stage-why-not`)
- [x] Trail teaser — last 3 brain events for focus SN
- [x] Share deep link — “Open share card” → `/subnet/{n}`

### §34-3 — Whale & rug desk ✅
- [x] Whale summary + alerts strip on Market drawer open
- [x] Rugger watch strip with focus-SN risk
- [x] Auto preset: top sellers on focus SN when drawer opens
- [x] Honest TaoStats empty copy with lever

### §34-4 — Pro learning story ✅
- [x] KPI filled from learning stats on first hydrate
- [x] Story strip promoted (`story-strip--prominent`)
- [x] Backtest council win-rate meter (one glance)
- [x] Council weights “Leaning X” copy

### §34-5 — Cull and consolidate ✅
- [x] Cockpit SSE guarded when no `.cockpit-card` DOM
- [x] Deleted orphan `daily_pick.html`, `data_fixer.js`
- [x] Staking / undervalued / radar labeled heuristic · `/api/subnets`

### §34-6 — Trailblazer polish ✅
- [x] Evidence / stage / investigation CSS + mobile pass
- [x] `conviction_tiers.js` + `data_freshness.js` in `scripts.html` before hydrate
- [x] `home_deferred.js` skips scripts already on page
- [x] Contract tests green

## Diagnosis (resolved)

The backend was ahead of the door. Graded picks, council, whales, investigation, pick-explain, brain letter, trail, readiness, and TaoStats are live — the homepage now surfaces them without spinner theater or drawer-only depth.

**North star met:** First viewport = SimiVision story (call or honest HOLD + why). Everything else is evidence.

## Explicitly out of scope

| Item | Why |
|------|-----|
| New prediction / crypto ledger / community judges | Backend R&D |
| Custom domain / Telegram delivery | Human infra |
| Redesign brand system | Council-first CSS only |
| Fake social / fake whales | Honest empty only |

## Success metric

A stranger lands on `/` for 10 seconds and can answer:

1. What is SimiVision saying today (LONG or honest HOLD + why)?
2. What evidence supports that (dissent / why-not / graded history)?
3. Where do I dig deeper (focus SN share, investigation, Pro)?
