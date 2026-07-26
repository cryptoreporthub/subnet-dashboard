# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-26T16:55:00Z  
**main:** `083f456` · G0 prod green · cockpit SSE fast path (#497)

## Active plan

**Canonical:** `cursor-agents-communication/gameplan-pump-site-undeniable.md` (audited 2026-07-24)  
**Status:** Waves **0–3 shipped** on `main` · Wave 4 YAGNI

| Wave | Status | Notes |
|------|--------|-------|
| 0 G0 | ✅ | `./scripts/g0_phone_qa.sh` prod green 2026-07-26 · 390px visual QA local pass |
| 1 P1–P3 | ✅ | Triad, hit-rate UI, size cliff (#410) |
| 2 P4–P5 | ✅ | Phase notify ✅ · wallet + day-whale + owner chips |
| 3 S1–S8 | ✅ | All merged #410; S3 who-sold = Prove-it button only |
| 4 | — | YAGNI |
| H1 | ✅ | cockpit.picks SSE + hour-watch rib (#497 SSE fix) |

**Execution history:** PR **#410** (Cursor Cloud Agent, 2026-07-22) + #430–#437 whale/Fly + #442–#446 site polish.

## Next slice queue

1. ~~Slice A–B~~ — attribution + pump desk (#414–#418)
2. ~~Slice R~~ — historical weight rebalance (#419)
3. ~~Slice M~~ — α pump overlay (#419)
4. ~~Full plan Waves 1–3~~ — #410 + follow-ups (#430–#446)
5. ~~G0 human~~ — prod + local 390px pass 2026-07-26
6. **Ops** — `fly scale count worker=1` when ready (#437 worker process)
7. Wave 4 — YAGNI

## Fix plan (done)

`cursor-agents-communication/quant-pump-desk-fix-plan.md` — Slices A–B + R + M shipped (#414–#419).

## Human follow-up

- `APP_BASE_URL=https://subnet-dashboard.fly.dev ./scripts/g0_phone_qa.sh`
- Phone QA 390px (Call + Lead + trust line)
- Optional: `fly scale count web=1 worker=1 --app subnet-dashboard`
- Env: `CONVICTION_ALERTS_ENABLED` / Telegram (off by default)
