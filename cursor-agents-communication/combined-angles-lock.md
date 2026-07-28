# Combined angles — Next up · Peers · Combined (experimental)

**Status:** SHIP (experimental)  
**Branch:** `cursor/echo-kin-pump-desk-1d2f`  
**Goal:** Transparent dual lines + one combined pick; backend tracks a slate for effectiveness.

## UI (separate questions)

| Line | Question | Shown |
|------|----------|-------|
| **Next up** | Who is closest to the pump gate? | up to 3 |
| **Peers** | Same pulse, quieter? | up to 3 |
| **Combined · experimental** | Timing×0.7 + peer×0.3 | **1** pick |

Each chip bar = **`to_lead_pct`** = candidate composite ÷ hero composite (capped 0–100) — how close they are to taking the **#1** spot, not absolute trigger %.

Hero **visual slot** (`pds-hero__visual`) is reserved empty for a future timer/art — do not stuff with clutter.

Copy must say **experimental** on Combined — not a settled claim.

## Backend tracking

- `data/pump_combined_calls.json` — each call stores **top 5** `tracked` + `next_up_top` + `peer_top` + shown
- Shown pick may freeze `pick_source=pump_combined_exp` (+2% / 1h), graded like pump_lead, **excluded from council weights**
- Dedup: same `shown_netuid` within 45m

## Equation

```
combined_pts = 0.70 * timing_pts + 0.30 * peer_pts
```

Tune weights only after graded n is meaningful.
