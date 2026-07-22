# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-22T20:40:00Z  
**main:** `28ef38a` (#414 + #415) — Slice A+B shipped and verified on Fly

## Next slice queue

1. ~~**Slice A**~~ — #414 unclassified attribution; prod `unclassified_count` live
2. ~~**Slice B**~~ — #415 pump unique copy + registry names + council votes hydrate
3. **Wave 4** — optional depth (YAGNI)
4. Optional experiment — publish gate 45% → 40% (not started)

## Gameplan

**Canonical:** `cursor-agents-communication/gameplan-pump-site-undeniable.md`  
**Fix plan:** `cursor-agents-communication/quant-pump-desk-fix-plan.md`

Peers: SubnetAIQ Pre-Pump Radar, TAO Subnet Radar, TaoDashboard, TaoDX.  
North star: frozen pre-pump claim → grade → n= trust → adapt; trader voice; no council weight contamination.

## Prod check (2026-07-22)

- `/api/learning/stats` → `unclassified_count` present (0 forward-only until new unmatched rows)
- `/api/pump-alerts` → unique CHASE RISK theses; SN54 = WebGenieAI
- `cockpit_hydrate.js` → always rewrite council votes when weights present

## Human follow-up

- Phone QA: Council votes under conviction show Quant/Hype/Dark Horse/Technical
- Env: `CONVICTION_ALERTS_ENABLED` / Telegram for Wave 2 push
