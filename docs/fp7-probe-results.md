# FP7 — Probe Results Log

This file is updated per probe run so each fly-diag trigger PR carries a real diff.

## Run 01 (2026-08-29)
- Trigger: fly-diag label (workflow fires from main; /jobs inventory posted as PR comment)
- Machine: v1 inline (web=1, worker=0), WORKER_HTTP_PORT=8081
- Expect: job_inventory() JSON with per-job next_run_time for classification
