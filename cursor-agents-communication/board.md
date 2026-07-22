# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-22T18:15:00Z  
**main:** merging `cursor/full-plan-execution-c9f5` (PR #410) — G0 + B0-c + H1 + Wave 2–3

## Next slice queue

1. **Deploy** — PR #410 merge → Fly deploy → G0 prod QA
2. **Wave 4** — optional depth (YAGNI until prod QA green)

## Gameplan

**Canonical:** `cursor-agents-communication/gameplan-pump-site-undeniable.md`

Peers: SubnetAIQ Pre-Pump Radar, TAO Subnet Radar, TaoDashboard, TaoDX.  
North star: frozen pre-pump claim → grade → n= trust → adapt; trader voice; no council weight contamination.

## Done (PR #410 — full plan execution)

- **G0** phone QA PASS on prod (SSR + triad API + daily-pick <2s)
- **B0-c** weight-nudge line wired from `expert_weight_deltas`
- **Wave 1 exit** verified on prod (triad fields, trust line path)
- **H1** `cockpit.picks` SSE + `#hour-watch-now` rib + O2 dedupe
- **P4** pump phase push (env-gated via conviction_alerts)
- **P5** wallet chips on pump cards (honest-empty)
- **S1–S8** all Wave 3 ACs (hero, weighed, LF, brain, portfolio, proof, council, footer)

## Done (recent on main)

- #405–#409 mobile SSR / quiet states / proof band / weight nudge (B0-0…c)
- #411 B0-d onboarding QA slice
- Trader hero, lead scanner, council closed loop, pump desk learning loop

## Human follow-up

- Phone QA 390px on subnet-dashboard.fly.dev after #410 deploy
- Env: `CONVICTION_ALERTS_ENABLED` / Telegram for Wave 2 push
