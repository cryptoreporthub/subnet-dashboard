# SD-105 concurrency preflight (no scoring)

Two `agent-sdk eval` slots in parallel (`--max-concurrency 1` each, separate state roots), pins aligned with R1-F3:

- Bot harness: `5d884c476340e2d8d678b20a9039e3a8900a6f10` (+ check_gate files at that pin)
- Fixtures: `36d724b1b131bfd755a07f4a6dd412aaf1a8c107`
- Run worktree: `be17418e8737d3e16bba6bdc923171d13da4f2b0`

## Run

```bash
git checkout be17418e8737d3e16bba6bdc923171d13da4f2b0
cd review-gate-bot && npm ci
export CURSOR_API_KEY=… R2_METHOD_ARM=A
bash exam-artifacts/concurrency-preflight/run-concurrency-preflight.sh
```

## Outputs

| File | Purpose |
|------|---------|
| `run-plan.json` | Pins, eval ids, wall cap |
| `concurrency-preflight-run.log` | Combined timeline |
| `summary.json` | Slot timings, exit codes, rate-limit grep |
| `runs/slot-*.json` | Raw eval JSON (not scored here) |
| `slots/slot-*.log` | Per-slot stdout/stderr |
