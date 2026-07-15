# STATUS — subnet-dashboard (Ditto boot card)

**Updated:** 2026-07-15T02:45:00Z · Agent `-6f98`  
**main:** `778ad13` (#221 merged)

## One-line

**Phase N/O Step 0 LOCKED. A/B unblocked. Grok = slow + medium default (escalate high only if needed).**

## Done (do not re-queue)

| Track | PRs |
|-------|-----|
| Phase A–B audit | #167–#185 |
| Phase C experience | #190–#192 |
| G7+G12 / council-first | #195 · #198 |
| Council picks + learning | **#200–#213** |
| Lazy OHLCV + badge polish | **#212** |
| Canvas radar (Chart.js removed) | **#215** |
| Social sentiment (message_intel) | **#217** |
| Fly keep-warm / 1GB + health gate | **#218** |
| N/O gameplan + token-save | **#221** |
| A2 `smoke` on `main` | verified |
| Stale open PRs closed | #101 · #110 · #112 · #129–#130 · #134 · #139 · #153 · #165–#166 · #184 |

## Ditto

- **Do:** read `board.md`, watch CI/Fly health, relay A/B to Step 0 spec
- **Do not:** re-open completed July 14 queue items; do not rebuild `signal_hub`

## Cursor

- **Active** — Phase N/O after Step 0 merge
- Git only; Ponytail minimal diff
- Grok: slow + medium default; high only if medium fails / unsatisfactory

## Phase N/O
- **APPROVED (2026-07-15)** · **Step 0 LOCKED** — `phase-n-o-step0-spec.md`
- Spec: `gameplan-N-O.md` + Step 0 decisions
- Models: Composer 2.5 default; **Grok slow + medium** — escalate to **high** only if medium fails or is unsatisfactory
- **A** (`-843d`): N2 → N3 → O1 → O4 → O5 (N2∥N3∥O1 OK)
- **B** (`-e78a`): **N4 → N1 → O2 → O3** (strict)
