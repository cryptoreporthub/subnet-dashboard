# Stage A raw eval outputs (published after RUN-READY model runs)

Each **invocation** (10 total, order from `run-plan.json` @ seed `20261102`) writes:

| Artifact | Path |
|----------|------|
| Raw eval JSON | `exam-artifacts/r24/runs/inv-<NN>-<PIN>-block<k>.json` |
| System blob SHA-256 | `exam-artifacts/r24/runs/inv-<NN>-sysprompt.sha256` |

- `<NN>` = `01`…`10` (`invocationIndex` in run-plan)
- `<PIN>` = `PRE` or `POST`
- `<k>` = block number `1`…`5`

Top-level field on each JSON file: `"pin": "PRE"|"POST"` (required — result `id`s carry no pin).

Scoring: `python3 exam-artifacts/r24/score_r24_runs.py` maps each `outputJson` path → pin and runs `score-r24-first-line.py` on the slot results inside.

Do not rename or edit files under `runs/` after Claude posts RUN-READY.
