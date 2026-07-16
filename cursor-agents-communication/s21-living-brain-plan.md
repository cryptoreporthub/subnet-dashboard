# §21 Living Brain — Automated Build Plan

**Status:** APPROVED 2026-07-16 (Ditto review incorporated)  
**Baseline:** `main` post-§20 (#286)  
**Prerequisite PRs:** #288 market drivers (merge first)

## Ditto red flags — MUST FIX BEFORE VISIBLE BRAIN UI

### RF-2 — Trust banner inflates accuracy
- **Issue:** Strategy doc showed "58% right" while live stats are ~44% (15/34 graded).
- **Fix:** ✅ `internal/learning/trust_stats.py` + `/api/learning/stats` → `trust_banner`, `brain_ui_ready`.
- **Rule:** Banner reads real resolver stats only. No hardcoded target numbers. Honest-empty when `graded < 30` or `expired_rate ≥ 10%`.

### RF-3 — Resolver / watchdog buried
- **Issue:** ~27% predictions expire ungraded; learning story built on sand.
- **Fix:** ✅ Promoted to **Sprint 0** (this PR): price lookup zero-volume median, 60m live fallback, `regrade_expired_predictions()`.
- **Gate:** `brain_ui_ready` on `/api/learning/stats` must be `true` before shipping L1–L5 trust/brain panels.

## Sprint order (revised)

| Phase | Slices | Gate | Status |
|-------|--------|------|--------|
| **S0** | RF-2 trust_stats API, RF-3 resolver fixes, regrade pass | `brain_ui_ready` or documented waiver | ✅ #289 merged |
| **S1** | #288 merge + L1 driver card UI, L2 story tags, L3 what's-working chips | S0 | ✅ #290 merged |
| **S2** | L4 trust banner UI, L5 mindmap story path | `trust_banner.ready` | 🔄 L4 honest-empty + L5 prep |
| **S3** | L6 signal_weights in scoring, L9 trail dual-write + updated_at fix | parallel with S2 | L6 ✅ #291 · L9 ✅ #290 |
| **S4** | L7–L8, L10–L14 | after S2 green | ✅ complete · RF-3 gate fix 🔄 |

## Wave A — Visible brain (blocked until S0 gate)

| Slice | Goal |
|-------|------|
| L1 | Driver card on daily pick + subnet report (price vs yield) |
| L2 | Story strip tags: yield_trap, price_momentum, signal |
| L3 | "What's working" chips from `/api/market-drivers` |
| L4 | Trust banner UI — **must bind `data.trust_banner` only** |
| L5 | Mindmap story path (linear cause chain for today's pick) |

## Wave B — Smarter brain

| Slice | Goal |
|-------|------|
| L6 | Apply signal_weights in state_vector scoring |
| L7 | Regime accuracy → REGIME_ADJUSTMENTS |
| L8 | Judge feedback into confidence |
| L9 | Fix trail dual-write + soul_map updated_at hardcode |
| L10 | Resolver watchdog surfaced in cockpit KPI |

## Wave C — Trailblazing

L11 Brain letter · L12 time-capsule replay · L13 chat presets · L14 shareable graded call card

## Preserve (net-new value)

- #288 market drivers (yield_trap, decompose_returns)
- L9 trail hygiene
- L12 time-capsule replay

## Contract

1. Branch `cursor/<slug>-9ce0`
2. Ready PR · merge when CI green
3. **Do not ship L4/L11 until RF-2 satisfied**
4. **Do not ship L1–L5 until `brain_ui_ready` or expired_rate < 10%**

## One-line agent prompt

```
§21 Sprint 0 first: RF-2/RF-3 (#289). Then merge #288. Run L1–L5 only when /api/learning/stats brain_ui_ready=true. Trust banner binds trust_banner object only — never hardcode accuracy. Composer 2.5-fast, ready PRs, auto-continue.
```
