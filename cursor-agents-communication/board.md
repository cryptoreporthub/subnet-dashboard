# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-24T06:30:00Z  
**main:** `d7eaf2a` (#453 inline worker v1 · post-#410 pump/site waves)

## Active plan

**Canonical:** `cursor-agents-communication/gameplan-pump-site-undeniable.md` (audited 2026-07-24)  
**Status:** Waves **0–3 shipped** on `main` · Wave 4 YAGNI

| Wave | Status | Notes |
|------|--------|-------|
| 0 G0 | ⚠️ | `scripts/g0_phone_qa.sh` ✅ · human 390px QA open |
| 1 P1–P3 | ✅ | Triad, hit-rate UI, size cliff (#410) |
| 2 P4–P5 | ⚠️ | Phase notify ✅ · wallet + day-whale chips ⚠️ · founder chip open |
| 3 S1–S8 | ⚠️ | All merged #410; S3 who-sold = Prove-it button only |
| 4 | — | YAGNI |

**Execution history:** PR **#410** (Cursor Cloud Agent, 2026-07-22) + #430–#437 whale/Fly + #442–#453 site polish + inline worker.

## Next slice queue

1. ~~Slice A–B~~ — attribution + pump desk (#414–#418)
2. ~~Slice R~~ — historical weight rebalance (#419)
3. ~~Slice M~~ — α pump overlay (#419)
4. ~~Full plan Waves 1–3~~ — #410 + follow-ups (#430–#453)
5. **Social evidence** — dossier crumb + desk-first homepage social (in flight)
6. **G0 human** — 390px phone QA sign-off (`./scripts/g0_phone_qa.sh` + manual)
7. **Ops** — inline worker via `ENABLE_INLINE_WORKER=1` (#453); **do not** `fly scale worker=1` without volume strategy
8. **Optional** — P5 founder/owner chip · publish gate 45%→40% experiment
9. Wave 4 — YAGNI

## Fix plan (done)

`cursor-agents-communication/quant-pump-desk-fix-plan.md` — Slices A–B + R + M shipped (#414–#419).

## Human follow-up

- `APP_BASE_URL=https://subnet-dashboard.fly.dev ./scripts/g0_phone_qa.sh`
- Phone QA 390px (Call + Lead + trust line)
- Optional: `fly scale count web=1 worker=1 --app subnet-dashboard`
- Env: `CONVICTION_ALERTS_ENABLED` / Telegram (off by default)
