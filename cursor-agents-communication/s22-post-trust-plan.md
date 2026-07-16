# §22 Post-Trust — resolver throughput + share polish

**Status:** in progress  
**Updated:** 2026-07-16

## Goal

Keep the §21 trust surfaces honest (RF-2) and unblocked (RF-3) in production by fixing resolver price coverage and boot latency.

## Slices

| Slice | State | Content |
|-------|-------|---------|
| **S22-1** | 🔄 | Scheduler passes **full subnet list** to `resolve_due_predictions` (batch stays telemetry-only) |
| **S22-2** | 🔄 | Boot `immediate=True` resolver tick so pending backlog clears on deploy |
| **S22-3** | ⏳ | OG image generation for graded-call share cards (optional) |

## RF gates (unchanged)

- Trust UI binds `/api/learning/stats` → `trust_banner` only.
- `brain_ui_ready` requires expired &lt;10%, graded ≥30, watchdog clear.

## Deferred

F7 DNS · A1b Telegram · S5 Discord/X
