# R1-BASE exam artifacts

**Harness pin:** `5d884c476340e2d8d678b20a9039e3a8900a6f10` (`cursor/r1-base-harness`)  
**Arm:** A (`R2_METHOD_ARM` unset or `A`)  
**Slots:** 21 cases × 3 iterations = 63 (iteration-major order)

## Files

| File | Purpose |
|------|---------|
| `run-plan.json` | Slot order + expected sysprompt/model gates |
| `r1-base-run-5d884c47.log` | Hermetic run log (3 waves) |
| `slot-audit-5d884c47.ndjson` | Per-slot: model, sysprompt sha/chars, `post_verdict` calls, case id + iteration |
| `runs/review-gate-hard-iter{1,2,3}-5d884c47.json` | Raw `agent-sdk eval --json` output (untouched) |

Scoring: Claude only (not done in this commit).
