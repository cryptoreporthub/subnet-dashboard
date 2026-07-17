# §34 — Front door catch-up (backend goldmine → visible product)

**Status:** ACTIVE  
**Updated:** 2026-07-17  
**Baseline:** `main` @ `4f43eaa` (post-§33)  
**Branch:** `cursor/s34-frontend-catchup-c3fd`

## Diagnosis

The backend is ahead of the door. Graded picks (453), council, whales, investigation, pick-explain, brain letter, trail, readiness, and TaoStats are live — but the homepage still feels empty because:

1. **Depth is demoted** — Pro / Market drawers hide the product one click away.
2. **Above-fold panels load late** — brain letter, what’s-working, freshness wait ~4s (`home_deferred.js`).
3. **Hydrate can wipe chrome** — `cockpit_hydrate.renderDailyPick` replaces `#council-stage-body` and can destroy trust / CTAs that SSR + `home_live_refresh` built.
4. **Rich APIs have no home surface** — whales (beyond leaderboards), ruggers desk, scenario memory, ops readiness, conviction-alert status.
5. **Honest HOLD ≠ empty product** — when daily pick is HOLD, the page should still show *why*, graded history, dissent, and what’s working — not a blank stage.

**North star:** First viewport = one clear SimiVision story (call or honest HOLD + why). Everything else is evidence for that story, not a landfill of equal-weight cards.

---

## Product principle (non-negotiable)

| Do | Don’t |
|----|-------|
| Surface **results that already exist** | Build new engines |
| One job per section | Add another drawer of orphan widgets |
| Promote share-page patterns home | Duplicate share as a second product |
| Honest empty with next lever | Spinner theater |
| Kill dead hydrate paths | Keep 12-card cockpit zombie |

---

## Slice queue

### §34-1 — Stop the empty theater (foundation)
**Goal:** First paint never looks broken.

| Work | Detail |
|------|--------|
| Fix council-stage hydrate | Patch fields only — never `innerHTML`-wipe `#council-stage-body` |
| Eager above-fold hydrate | Brain letter + what’s-working + freshness load with first paint (not deferred 4s) |
| HOLD as a product | When action=HOLD: show candidate, confidence vs gate, pick-explain blockers, last graded outcome |
| Trust strip | Wire `/api/ops/readiness` next to freshness: graded count, feed source, resolver running — one line |

**Done when:** Cold load shows council stage + Living Focus + brain letter without a 4s blank; HOLD still feels informative.

### §34-2 — Living Focus becomes the evidence desk
**Goal:** The focus subnet panel is the trailblazer surface.

| Work | Detail |
|------|--------|
| Expand chips → rows | Scenario memory, ruggers, autopsy: 1-line evidence each (not 3 silent chips) |
| Pick-explain on stage | Mirror Living Focus blockers onto council stage “Why not LONG” |
| Trail teaser | Last 3 mindmap trail events for focus SN (link → full trail in Pro) |
| Share deep link | “Open share card” → `/subnet/{n}` (already rich) |

**Done when:** Focus SN with data shows dissent + why-not + one risk + one lesson without opening drawers.

### §34-3 — Whale & rug desk (Market drawer → usable)
**Goal:** Investigation panel stops looking like a blank form.

| Work | Detail |
|------|--------|
| Default whale summary | On drawer open: `/api/whales/summary` + top alerts (not only leaderboards after click) |
| Rugger watch strip | `/api/ruggers/summary` or focus-SN rugger chip → expandable |
| Preset probes | One-click: “Top sellers on focus SN”, “Wallet from URL `?wallet=`” (already partly wired) |
| Honest TaoStats | If dark: one banner with lever (`TAOSTATS_API_KEY`) — already true in ops |

**Done when:** Opening Market & tools shows whale/risk signal without requiring a typed query first.

### §34-4 — Pro cockpit tells the learning story
**Goal:** Graded goldmine is readable.

| Work | Detail |
|------|--------|
| KPI always filled | Graded / accuracy / pending from learning stats on first hydrate |
| Story strip first | Promote last graded outcomes above SimiVision warming cards |
| Backtest one-glance | Council win rate + n as a single meter, not an empty table |
| Weights with lean | Expert bars + “leaning X” copy (T1 already exists — ensure visible) |

**Done when:** Pro drawer never opens to three “warming up” empty cards when graded > 0.

### §34-5 — Cull and consolidate
**Goal:** Fewer surfaces, more signal.

| Work | Detail |
|------|--------|
| Delete or wire dead cockpit cards | `/api/cockpit/sections` + SSE path with no DOM — wire or remove |
| Orphan cleanup | `daily_pick.html` orphan, unused `data_fixer.js` |
| Heuristic panels | Staking / undervalued / radar: demote further or label “heuristic from /api/subnets” |
| Message-intel | Keep honest-empty; don’t fake social — one status line + last ingest time |

**Done when:** No hydrate path writes to missing DOM; Market drawer has ≤1 clearly-labeled heuristic section.

### §34-6 — Trailblazer polish (presence, not fluff)
**Goal:** The door feels alive when the brain is alive.

| Work | Detail |
|------|--------|
| Motion budget | 2–3 intentional motions: stage reveal, focus chip enter, trail tick |
| Empty-state copy pass | Every empty string names the real next lever (resolver / gate / TaoStats / feed) |
| Mobile pass | Council stage + Living Focus readable without horizontal scroll |
| Contract | Any new route → `tests/test_endpoint_contract.py`; UI smoke for HOLD + graded paths |

**Done when:** HOLD day and LONG day both feel like a product, not a skeleton.

---

## Explicitly out of scope

| Item | Why |
|------|-----|
| New prediction / crypto ledger / community judges | Backend R&D, not door catch-up |
| Custom domain / Telegram delivery | Human infra (H1/H2) |
| Redesign brand system | Work inside existing council-first CSS |
| Fake social / fake whales | Honest empty only |

---

## Suggested build order

```
§34-1 foundation (hydrate + HOLD + readiness strip)
  → §34-2 Living Focus evidence
    → §34-4 Pro learning story   } can parallel after 34-1
    → §34-3 Whale/rug desk       }
      → §34-5 cull
        → §34-6 polish
```

## Agent prompt

```
§34 FRONT DOOR CATCH-UP:
- Read s34-frontend-catchup-plan.md + board.md
- Branch: cursor/s34-frontend-catchup-c3fd
- One slice at a time; start §34-1
- No data/*.json · no new deps · ponytail
- Fix hydrate wipe before adding panels
- Contract tests green; prefer patch over redesign
```

## Success metric

A stranger lands on `/` for 10 seconds and can answer:

1. What is SimiVision saying today (LONG or honest HOLD + why)?
2. What evidence supports that (dissent / why-not / graded history)?
3. Where do I dig deeper (focus SN share, investigation, Pro)?

If they can’t, the door isn’t done.
