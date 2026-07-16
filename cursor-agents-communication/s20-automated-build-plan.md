# §20 — Agent-only polish (no human gates)

**Status:** APPROVED 2026-07-16  
**main baseline:** `64b4d6d` (#284 §19 M3+U5p)  
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
| **T1** | Doc sync | STATUS + board: §18 ✅ §19 ✅ (#282–#284); §20 active | `cursor-agents-communication/*` |
| **T2** | Letter export UI | Copy/download markdown for weekly + daily letter panels (no email/SMTP) | `static/js`, templates |
| **T3** | verify_prod | Add checks: message-intel status, social summary, `/api/report/1` | `scripts/verify_prod.sh` |
| **T4** | Report UX | Subnet report panel: loading/error states + keyboard a11y (build on #277) | `static/js/subnet_report.js` |

**Stop human only if:** CI fail · On-Demand $ beyond Pro+

## Contract

1. Branch `cursor/<slug>-9ce0` off latest `main`
2. Ready PR · merge when CI green · auto-continue T1→T4
3. No `data/*.json` · no new deps · ponytail minimal diff
