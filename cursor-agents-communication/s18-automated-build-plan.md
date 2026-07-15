# §18 — Production depth (post-§17)

**Status:** APPROVED 2026-07-15 · human QB  
**main baseline:** `8075bda` (#274 U4 merged · §17 complete)  
**Models:** Composer 2.5-fast build · Grok subagent slow+low/med only if DESIGN

## Queue (sequential · unattended)

| # | Slice | Goal | Stop human? |
|---|-------|------|-------------|
| **H1** | Merge **#265** | `.cursorignore` + token-budget rules on main | No |
| **H2** | Close **#240** | Stale docs PR — superseded | No |
| **H3** | STATUS/board | §17 closed + U4 #274; §18 in progress | No |
| **A1** | Alert delivery docs + Fly wiring | `CONVICTION_ALERT_DELIVERY` telegram/webhook; `DEPLOY.md` secrets section | **Yes** — Fly secrets |
| **A2** | Alert test path | Dry-run + status docs; `verify_prod.sh` conviction-alerts line | No |
| **B1** | O3 report UI | Render `GET /api/report/{netuid}` — template/static + link from subnet row | No |
| **C1** | Message-intel listener | **WAIT** — human provides `TELEGRAM_API_ID/HASH` | **Yes** — skip until creds |

**Skip unless asked:** F7 DNS · B12 · S5 Discord · weekly letter email

## Contract (each slice)

1. Branch `cursor/<slug>-6f98` off latest `main`
2. Ready PR (not draft) · merge when CI green · auto-continue next slice
3. No `data/*.json` commits · ponytail minimal diff
4. On-Demand $ beyond Pro+ pool → stop and tell human

## A1 human secrets (when prompted)

```bash
flyctl secrets set CONVICTION_ALERT_DELIVERY=telegram \
  TELEGRAM_BOT_TOKEN=<bot> TELEGRAM_ALERT_CHAT_ID=<chat> --app subnet-dashboard
```

Optional webhook: `CONVICTION_ALERT_DELIVERY=webhook` + `CONVICTION_ALERT_WEBHOOK_URL=...`
