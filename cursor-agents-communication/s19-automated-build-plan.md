# §19 — Live intel surface + launch tail

**Status:** IN PROGRESS 2026-07-16 · post-§18  
**main baseline:** `6b37876` + #279–#281  
**Models:** Composer 2.5-fast build · Grok subagent DESIGN only if ambiguous

## Queue (sequential · unattended)

| # | Slice | Goal | Stop human? |
|---|-------|------|-------------|
| **M1** | Message-intel feed UI | ✅ #282 | — |
| **M2** | Social panel wire | ✅ #283 | — |
| **M3** | Intel live refresh | ✅ #284 |
| **U5p** | Launch meta prep | ✅ #284 |
| **F7** | Custom domain DNS | deferred — human when ready | **Yes** |
| **B12** | U5 launch polish | after F7 | **Yes** |
| **A1b** | Conviction delivery | `CONVICTION_ALERT_DELIVERY` + bot secrets (optional) | **Yes** — BotFather |

**Skip unless asked:** S5 Discord/X · Twitter API · weekly letter **email** · B12 · F7 DNS

## Contract

1. Branch `cursor/<slug>-9ce0` off latest `main`
2. Ready PR · merge when CI green · auto-continue
3. No `data/*.json` commits · ponytail minimal diff
4. templates/static only for M1/M2 unless new route required

## M1 acceptance

- Market drawer shows listener status + recent messages (textContent-safe)
- Empty + `listener.live` → explicit “waiting for group traffic” (not fake rows)
- Contract test unchanged
