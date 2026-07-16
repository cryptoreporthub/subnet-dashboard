# §19 — Live intel surface + launch tail

**Status:** IN PROGRESS 2026-07-16 · post-§18  
**main baseline:** `6b37876` + #279–#281  
**Models:** Composer 2.5-fast build · Grok subagent DESIGN only if ambiguous

## Queue (sequential · unattended)

| # | Slice | Goal | Stop human? |
|---|-------|------|-------------|
| **M1** | Message-intel feed UI | Render `GET /api/message-intel` in market drawer; honest-empty when listener live but quiet | No |
| **M2** | Social panel wire | Prefer live intel rows in social cards when store has data | No |
| **F7** | Custom domain DNS | `dashboard.cryptoreporthub.com` per `DEPLOY.md` / `f7-custom-domain.sh` | **Yes** — registrar |
| **B12** | U5 launch polish | Brand/meta polish on custom domain | **Yes** — after F7 |
| **A1b** | Conviction delivery | `CONVICTION_ALERT_DELIVERY` + bot secrets (optional) | **Yes** — BotFather |

**Skip unless asked:** S5 Discord/X · weekly letter email · B12 before F7

## Contract

1. Branch `cursor/<slug>-9ce0` off latest `main`
2. Ready PR · merge when CI green · auto-continue
3. No `data/*.json` commits · ponytail minimal diff
4. templates/static only for M1/M2 unless new route required

## M1 acceptance

- Market drawer shows listener status + recent messages (textContent-safe)
- Empty + `listener.live` → explicit “waiting for group traffic” (not fake rows)
- Contract test unchanged
