# Loop stall guard calibration — P4b (2026-10-10)

**Evidence window:** Soak 4 on prod `12c85d1d` (2026-10-09 ~3:12–5:18 PM PT). Axiom APL **403**; Fly logs + machine events substitute.

## Observed prod (Fly)

| Signal | Value | Source |
|--------|-------|--------|
| `pump_ladder` heavy_job hold | ~249s (~4.2 min) | MC soak 4 interim log |
| Resolver tick success | ~38.6s | MC soak 4 interim log |
| `live_subnets` sync | 90s timeout warning (worker continues) | Fly log @ soak close |
| Stall-guard strike/kill | **none** in available buffers | Soak 4 final packet |
| OOM / exit 137 | **none** | Machine events |

## Committed defaults after P4b

| Knob | Before | After | Rationale |
|------|--------|-------|-----------|
| `LOOP_STALL_GUARD_CONSECUTIVE_CHECKS` | 2 | **3** | Extra strike before `os._exit` during long snapshot/resolver work; **does not** change `LOOP_STALL_GUARD_KILL`. |
| `LOOP_STALL_GUARD_RESOLVER_REVIVE_SECONDS` | 1800 | **2400** | Align with 15m resolver refresh × ~1.5 cycles + long `pump_ladder` holds without premature revive. |

Unchanged: `LOOP_STALL_GUARD_KILL`, daily-pick 90s timeout, `MAX_SNAPSHOT_AGE_SECONDS` (5400), `MAX_RESOLVER_AGE_SECONDS` (21600).

## Fly override (optional)

Tune without code deploy via secrets only if prod shows false revive/strike after Deploy B.
