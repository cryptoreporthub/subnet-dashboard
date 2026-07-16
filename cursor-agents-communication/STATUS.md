# STATUS — subnet-dashboard (Ditto boot card)

**Updated:** 2026-07-16T02:20:00Z  
**main:** `64b4d6d` (#284)

## One-line

**§18–§19 COMPLETE on main. §20 agent-only polish (no DNS / no Twitter / no bot secrets).**

## Done

| Phase | PRs |
|-------|-----|
| **§17** | #267–#271, #274 |
| **§18** | #275–#281, #277 report UI, C1 #279–#280 |
| **§19** | #282–#284 (intel feed, social, live refresh, OG meta) |

## §20 queue (agent-only)

See **`s20-automated-build-plan.md`**: T1 doc sync → T2 letter export → T3 verify_prod → T4 report UX.

## Deferred (human)

| Item | When |
|------|------|
| **F7 DNS** | `./scripts/f7-custom-domain.sh` |
| **A1b alerts** | BotFather + `flyctl secrets` |
| **S5 Discord/X** | not planned |

**Billing watch:** On-Demand **$** beyond Pro+ → tell human.
