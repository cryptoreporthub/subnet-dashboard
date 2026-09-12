# Deploy vehicle — Phase A: resolver stage profiling (instrumentation-only)

- Date: 2026-09-03
- Purpose: deploy main @ 6a38fae7 (squash merge of PR #1173) to Fly.io via the fly-deploy label path.
- Content delta vs main: this doc only. Code deployed = main @ 6a38fae7.
- PR #1173 verified pre-merge: six-file scope, additive _CycleTiming instrumentation (resolve_due_ms / expire_stale_ms / total_cycle_ms), count-only abandoned_live, LF-normalized, routes.py restored additive (+15/-1).
- Deploy authorization: user approved label-path deploy in Ditto thread 2026-09-03 ("Ok take care of it and the checks").
- Incident constraint honored: push-to-main deploy remains disabled (INCIDENT 2026-08-19); this PR uses the fly-deploy label trigger.
- Post-deploy checks: /health 200, homepage render, /pump fresh alerts, /api/learning/health 200 (not 422), resolver logs emit stage_timing_ms keys.
