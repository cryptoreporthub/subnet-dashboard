# §21 Living Brain — Automated Build Plan

**Status:** ✅ COMPLETE 2026-07-16 (`main` @ `310ded6`)  
**Baseline:** `main` post-§20 (#286)

## Ditto red flags — resolved

### RF-2 — Trust banner inflates accuracy
- **Fix:** ✅ `internal/learning/trust_stats.py` + `/api/learning/stats` → `trust_banner`, `brain_ui_ready`.
- **Rule:** Banner reads real resolver stats only. Honest-empty when `graded < 30` or `expired_rate ≥ 10%`.

### RF-3 — Resolver / watchdog buried
- **Fix:** ✅ S0 (#289) + gate fix (#296): regrade merge on save, watchdog aligns with resolve grace.
- **Gate:** `brain_ui_ready` unlocks when graded ≥30, expired &lt;10%, watchdog clear.

## Sprint order (final)

| Phase | Slices | PRs | Status |
|-------|--------|-----|--------|
| **S0** | RF-2 trust_stats, RF-3 resolver/regrade | #289 | ✅ |
| **S1** | #288 + L1 driver card, L2 story tags, L3 chips | #288, #290 | ✅ |
| **S2** | L4 trust banner, L5 mindmap story path | #293 | ✅ |
| **S3** | L6 signal_weights, L9 trail hygiene | #291, #290 | ✅ |
| **S4** | L7–L8, L10–L14 | #292–#296 | ✅ |
| **Gate** | RF-3 regrade clobber + watchdog | #296 | ✅ |

## Slice checklist

| Slice | Goal | PR |
|-------|------|-----|
| L1 | Driver card (price vs yield) | #290 |
| L2 | Story strip tags | #290 |
| L3 | What's-working chips | #290 |
| L4 | Trust banner UI (RF-2) | #293 |
| L5 | Mindmap story path | #293 |
| L6 | signal_weights in scoring | #291 |
| L7 | Learned regime adjustments | #293 |
| L8 | Judge feedback → confidence | #294 |
| L9 | Trail dual-write fix | #290 |
| L10 | Watchdog KPI strip | #292 |
| L11 | Brain letter | #295 |
| L12 | Time-capsule replay | #294 |
| L13 | Chat presets | #293 |
| L14 | Shareable graded call | #294 lite · #300 SVG · #301 PNG ✅ |

## Home stack (shipped)

Council stage → trust banner → driver card → story strip → story path → brain letter → what's-working → Pro cockpit

## Contract (historical)

1. Branch `cursor/<slug>-9ce0`
2. Ready PR · merge when CI green
3. Trust surfaces bind `trust_banner` only — never hardcode accuracy

## Next

**§22** — await human queue after L14 visual card merges.
