# Master automated gameplan (§29 + §30)

**Status:** ACTIVE  
**Updated:** 2026-07-17  
**Baseline:** `main` @ `6c9b057` (post-#312 §27+§28)  
**Branch:** `cursor/s30-living-brain-c3fd`

## Agent prompt

```
MASTER AUTOMATION:
- Read board.md → this file → active slice AC only.
- One slice per turn when unattended; this branch stacks §30 then §29.
- Ready PR · merge when CI green · auto-continue.
- No data/*.json commits · RF-2 · nudge_expert is online weight authority.
- Grok slow+low for AC fail / ambiguous design only; med if stuck.
```

## Unified queue (sequential)

| # | Slice | Fixes / scope | State |
|---|-------|---------------|-------|
| **§30-0** | Docs + board sync | audit, plans, board | this PR |
| **§30-1** | Living Focus correctness | LB-1, LB-2, LB-3 | this PR |
| **§30-2** | Focus-scoped chips | LB-4 | this PR |
| **§30-3** | Trail: signal weights + feedback | LB-7, LB-9 | this PR |
| **§30-4** | Message-intel weight quarantine | LB-8 | this PR |
| **§30-5** | Alignment → nudge_expert | LB-8 | this PR |
| **§30-6** | Disposition soft-feature in scoring | LB-5 | this PR |
| **§30-7** | Scenario outcome soft-boost | LB-6 | this PR |
| **§30-8** | RF-2 cockpit KPI honesty | LB-14 | this PR |
| **§30-9** | Homepage fetch dedupe | LB-11 | this PR |
| **§30-10** | Shared subnet feed picks + judges | LB-16 | this PR |
| **§29-1** | verify_prod shareable routes | backlog | this PR |
| **§29-3** | Name integrity guard | B1–B4 | this PR |
| **§29-4** | Living Focus weight lean UI | T1 | merged into §30-1 |
| **§29-9a** | Living brain tests | — | this PR |

**Defer:** §29-5–8, §29-9b, §29-10, H1–H6, D1–D7, LB-10/13/17.

## References

- `living-brain-audit.md` — findings LB-1…LB-17
- `post-s30-living-brain-plan.md` — §30 slice AC
- `post-s29-automated-build-plan.md` — §29 polish queue
- `post-s28-backlog.md` — full checklist
