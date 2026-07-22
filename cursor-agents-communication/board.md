# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-22T15:35:00Z  
**main:** `cdd3806` · #402 names/deltas + #403 H1 LOCK merged

## Next slice queue

1. **G0** — Phone QA 390px on prod (automated `verify_prod.sh` ✅ · daily-pick ~0.18s ✅ · triad on pump cards ✅ · **human 390px pass still open**)
2. **Wave 1 exit** — mark complete after G0 (P1–P3 code on main; pump trust line honest-empty until lead grades land)
3. **H1** — Hour watch live bus (`h1-hour-watch-live-lock.md`) — **LOCK on main**; execute after G0 + Wave 1 exit + B0-0
4. **Wave 2** — P4 push alerts · P5 lead-wallet/founder chips
5. **Wave 3** — Site section upgrades S1→S8 (3 ACs each)
6. **Telegram** — H4 session bootstrap + feed honesty (may share P4)

## Gameplan

**Canonical:** `cursor-agents-communication/gameplan-pump-site-undeniable.md`

Peers: SubnetAIQ Pre-Pump Radar, TAO Subnet Radar, TaoDashboard, TaoDX.  
North star: frozen pre-pump claim → grade → n= trust → adapt; trader voice; no council weight contamination.

## Stale PRs (superseded — close on GitHub)

| PR | Reason |
|----|--------|
| #359, #360 | K3-7 shipped (#361); lock docs archived in repo |
| #331 | Above-fold + apiFetchJson already on main |
| #340 | Dark horse repair in `weights.py`; test added in cleanup PR |
| #313, #309 | §27–§30 docs already on main |

## Done (recent)

- #391–#394 hero hydrate / fast daily-pick / weighed deferred
- #395 hero trust polish + pump step 0 `phase_at_prediction`
- #396 `pump_lead` ledger at phase entry
- #397 claim grading (+2%/1h), desk trust line, `pump_calibration` adapt n≥30

## Shipped on main

Trader hero, lead scanner (WARMING UP / BUILDING / JUST STARTED / CHASE RISK), council closed loop, pump desk learning loop (ledger → grade → trust → calibrate).

## Human follow-up

- Approve / amend `gameplan-pump-site-undeniable.md`
- Phone QA 390px on subnet-dashboard.fly.dev after #397 deploy
- Env: `CONVICTION_ALERTS_ENABLED` / Telegram for Wave 2 push
