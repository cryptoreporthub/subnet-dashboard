# Phase §16 — Close the trust gap

**Status:** DRAFT 2026-07-15 · Ditto-scoped · **do not implement until approved**  
**After:** Phase N/O (#227 + #228) · Phase P (#232 + #237)  
**Companion (what this phase deliberately excludes):** `gameplan-beyond-16.md` (§17)

## Why

N2 partially filled scenario outcomes; P3 left `hybrid_score()` as a stub. §16 closes that trust gap only — small and contained.

## Three steps (sequential)

| Slice | What |
|-------|------|
| **16.1** | Fill outcome gaps — record right/wrong for every past pick so nothing is blank (finish what Phase N started) |
| **16.2** | Replace the placeholder `hybrid_score` with a real, data-backed score using that history — **only if enough data**; otherwise honest “not enough data yet” (no fake number) |
| **16.3** | Re-run the performance check and report the real win rate after calibration |

**Owner:** Agent A (`-843d`). **Order:** 16.1 → 16.2 → 16.3.

## Explicitly out of scope (→ §17)

Ditto deliberately left these out of §16. They live in **`gameplan-beyond-16.md`**:

- New big features
- UI redesigns
- Extra signals

## Non-negotiables

- Honest-empty > decorative summaries > 500s
- No threshold gaming
- No `data/*.json` churn in commits
