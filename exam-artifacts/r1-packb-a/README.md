# R1-A2 pack B exam artifacts (`exam-artifacts/r1-packb-a/`)

Arm **A**, 48 fixtures × 3 iterations (144 slots), harness pin **`5d884c47`**, fixture pin **`7c7100a9`**, V3 gate schema.

## Deviation (2026-11-03)

1. **Failure:** After WAVE_1 completed, `extract-slot-audit.mjs` was missing on disk → `MODULE_NOT_FOUND`; slot-audit stayed empty; waves 2–3 never started.
2. **Resume:** `resume-r1-packb-a2-waves23.sh` — keep WAVE_1 raw JSON; **do not** re-run iteration 1 eval slots.
3. **Backfill:** WAVE_1 slot-audit lines written by `backfill-wave1-slot-audit.mjs` from iter1 JSON with `"backfilled": true` and `backfillDerivation`; **V1** (`syspromptChars`, `syspromptSha256`, `model`) taken only from **wave-1 run log preflight lines** (first block after initial `=== R1-A2 pack B run start`), not from resume preflight or eval JSON.
4. **Waves 2–3 (slot-capped rerun):** `run-wave-slots-capped.sh` — one eval id per slot, **15m wall clock** (`SLOT_WALL_SEC=900`); log `slot_timeout case=… iteration=…`; capped slot → audit `v2Outcome: "NO_POST"` (no silent retry). Live slots append via `append-slot-audit-line.mjs` with `slotStartedAt` / `slotEndedAt`.
5. **Wave-2 second hang:** After **`WAVE_2_HUNG_KILLED`** appears **twice** in the run log, **STOP** — do not restart the whole wave again; report stuck `eval_id` / case on #1544. (First hang: batch eval ~70m with no iter2 file, 2026-11-03T18:00:52Z.)

**Claude fallback (only if wave-1 V1 preflight in log is invalid):** score iterations 2–3 only (96 slots); family rule denominator **12** not 18. Document in landing comment if invoked.

Publish bar: **144/144** audit lines + three wave JSONs under `runs/`; no scoring in repo.
