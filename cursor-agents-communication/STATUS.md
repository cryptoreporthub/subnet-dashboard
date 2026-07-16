# STATUS — subnet-dashboard (Ditto boot card)

**Updated:** 2026-07-16T09:15:00Z  
**main:** `310ded6` (#296 RF-3 gate fix)

## One-line

**§21 Living Brain COMPLETE** — trust gate unblocks after resolver tick (`brain_ui_ready` when expired &lt;10%, n≥30, watchdog clear).

## Done

| Phase | PRs |
|-------|-----|
| **§17** | #267–#271, #274 |
| **§18** | #275–#281, #277 |
| **§19** | #282–#284 |
| **§20** | #286 (T1–T4 letter export · verify_prod · report UX) |
| **§21** | #288–#296 (Living Brain — see `s21-living-brain-plan.md`) |

## §21 summary (merged)

| PR | Content |
|----|---------|
| **#288** | Market drivers API (yield_trap, decompose_returns) |
| **#289** | S0 RF-2 trust_stats + RF-3 resolver/regrade |
| **#290** | L1–L3 UI + L9 trail hygiene |
| **#291** | L6 signal_weights in scoring |
| **#292** | L10 watchdog KPI strip |
| **#293** | L4 trust banner · L5 story path · L7 regime · L13 chat presets |
| **#294** | L8 judge feedback · L12 time-capsule · L14 lite (clipboard) |
| **#295** | L11 Brain letter |
| **#296** | RF-3 regrade clobber fix + watchdog grace alignment |

## Active plan

**`cursor-agents-communication/s21-living-brain-plan.md`** — product spec (§21 done).

## Next queue

| Slice | State |
|-------|--------|
| **L14 full** | Visual graded-call card | 🔄 this PR |
| **Post-§21** | Await human direction · Fly deploy picks up #296 |

## Gate (RF-2 / RF-3)

- Trust surfaces bind `/api/learning/stats` → `trust_banner` only — never hardcode accuracy.
- After #296 + one resolver scheduler tick: `brain_ui_ready` can be `true` (expired &lt;10%, graded ≥30, watchdog clear).

## Deferred (human)

F7 DNS · A1b bot · S5 Discord/X — **skipped**

**Billing watch:** On-Demand **$** beyond Pro+ → tell human.
