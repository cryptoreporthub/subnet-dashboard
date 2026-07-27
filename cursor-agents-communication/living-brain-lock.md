# Living Brain — build lock (post-§30)

**Updated:** 2026-07-27  
**Owner:** Agent A (learning / council / Living Focus / mindmap)  
**Baseline:** `main` post-#540 · learning loop green · §30-1–10 shipped

## Do not rebuild (already on main)

| Area | PRs / notes |
|------|-------------|
| Focus calibration + `?focus=` | §30-1 |
| Focus-scoped chips | §30-2 (#529) |
| Trail signal weights + feedback | §30-3 |
| Message-intel quarantine | §30-4 |
| Alignment nudge hygiene | §30-5 |
| Disposition + scenario soft score | §30-6–7 |
| RF-2 KPI honesty | §30-8 (#529) |
| Homepage trail dedupe | §30-9 (#526–527) |
| Shared subnet feed | §30-10 |
| Learning loop + snapshot | #531–541 |
| Mid-cap scoring cap | #540 |

## LB-12 — DONE (#542 on `main`)

- `/api/mindmap/graph?focus=` scopes trail + dispositions to focus netuid
- `/api/story-strip?focus=` scopes resolved outcomes to focus netuid
- `mindmap_graph.js` refetches on `living-focus:change`

## Active — Track 1 (calibration + LONG publish)

**Branch:** `cursor/track1-long-unlock-4988` — stale boot HOLD regen, shortlist cache, HOLD-day alternatives UX (cherry from #487).
- Cockpit story strip refetches on focus change
- Honest empty when focus has no trail/outcomes yet

**Files:** `internal/mindmap/graph.py`, `internal/mindmap/routes.py`, `internal/analytics/story_strip.py`, `internal/learning/routes.py`, `static/js/mindmap_graph.js`, `static/js/cockpit_hydrate.js`

## Defer (other agents — do not duplicate)

| ID | Item | Owner hint |
|----|------|------------|
| LB-10 | Stub brain recommendations | delete or wire — low priority |
| LB-13 | Dual paper portfolios | product decision |
| LB-17 | Pick history → score | needs careful test |
| Track 1 | Confidence + LONG (#491/#487) | **separate** — touches `confidence_calibration.py`, not graph |
| Prod tune | Close stale PRs | human/docs |

## Conflict surface

- `living_focus.js`, `cockpit_hydrate.js`, `internal/mindmap/*`, `story_strip.py` — **one agent at a time**
- `server.py` + `test_endpoint_contract.py` — rebase if parallel PRs

## Verify after merge

```bash
pytest tests/test_living_brain.py tests/test_phase_g_mindmap_graph.py tests/test_u2_story_strip.py -q
APP_BASE_URL=https://subnet-dashboard.fly.dev ./scripts/check_learning_loop.sh
APP_BASE_URL=https://subnet-dashboard.fly.dev ./scripts/verify_prod.sh
```
