# Hero + mindmap 390px sign-off pack — 2026-08-02

**main at run:** `4cbfe94` (#765 soul_map deepcopy)  
**Prod:** `https://subnet-dashboard.fly.dev`  
**Agent script:** `BASE=… ./scripts/g0_phone_qa.sh`  
**Human sign-off:** deferred — layout change in progress; re-run g0 after layout lands

## Automated SSR / marker checks

| Check | Result |
|-------|--------|
| Hydrate flag | PASS |
| Hero `#k3-dossier` | PASS |
| Living Focus section + four-beat | PASS |
| Brain letter / proof band / pump desk | PASS |
| No convening / eternal loading / warming theater | PASS |
| Dual judge labels + track-record nudge hook | PASS |
| Hour watch rib | PASS |
| SS-TG W0 markers (section, brand, t.me, yesterday, HC, proof) | PASS |
| `GET /api/daily-pick` | OK — HOLD |
| `GET /api/pump-alerts` | OK — `status=success` count=8 desk=True |
| `babysit_phase.sh sprint` | PASS — EXIT 0 (WARN: og:image, graded=0) |

## Hero ACs (agent SSR / API)

| AC | Notes |
|----|-------|
| 1–3 Dossier present, conf state honesty | SSR `#k3-dossier` PASS; prior H1/H2/#736 on main |
| 4 Horizon / sample-size | Shipped #736 |
| 5 Mindmap graph/trail | #744 graph no longer builds full state; trail LB-11 #748 |
| 6 Focus strip | Living Focus PASS |
| 7 390px human glance | **PENDING human** — after layout change; agent g0 PASS |

## Human sign-off (required)

- [ ] Cold load at ~390px: hero claim readable; orb not fake-0% when confidence missing
- [ ] HOLD/LONG chip colors still correct after #746 badge dedupe
- [ ] Mindmap integration-status legend visible when graph loads
- [ ] Comment on this PR or Ditto: **H1-style GO** / HOLD with notes

No code patches from this run. Re-run g0 after layout PR merges, then human 390px glance.
