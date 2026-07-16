# §20 — Agent-only polish (no human gates)

**Status:** COMPLETE 2026-07-16  
**main baseline:** `0e29e5d` (#285 §20 plan)  
**Models:** Composer 2.5-fast · Grok subagent DESIGN only if ambiguous

## Human gates — SKIP entire phase

| Skip | Why |
|------|-----|
| **F7 / B12** | Custom domain — human DNS |
| **A1b** | Conviction alerts — BotFather + Fly secrets |
| **S5 / Discord / X / Twitter API** | External creds |
| **C1 bootstrap** | Done on Fly — no redo |

## Queue (sequential · unattended)

| # | Slice | Goal | Files |
|---|-------|------|-------|
| **T1** | Doc sync | ✅ STATUS + board: §18 ✅ §19 ✅ (#282–#284); §20 complete | `cursor-agents-communication/*` |
| **T2** | Letter export UI | ✅ copy/download markdown for weekly + daily letter panels | `static/js/letter_export.js`, templates |
| **T3** | verify_prod | ✅ message-intel status, social summary, `/api/report/1`; fixed backtest curl | `scripts/verify_prod.sh` |
| **T4** | Report UX | ✅ loading/error states + keyboard a11y on subnet report | `static/js/subnet_report.js` |

**Stop human only if:** CI fail · On-Demand $ beyond Pro+

## Contract

1. Branch `cursor/<slug>-9ce0` off latest `main`
2. Ready PR · merge when CI green · auto-continue T1→T4
3. No `data/*.json` · no new deps · ponytail minimal diff
