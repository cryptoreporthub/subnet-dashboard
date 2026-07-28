# Learning loop verdict fix — orphan web data + deploy check

**Status:** SHIP  
**Branch:** `cursor/learning-loop-verdict-fix-1d2f`  
**Symptom:** Fly Deploy failed `Learning loop post-deploy check` with  
`FAIL — pending work but resolver tick older than 2x refresh` even when  
`worker_peer.alive: true` and status `degraded`.

## Root causes

1. **check_learning_loop.sh** exited FAIL on stale tick *before* handling `status=degraded` (normal post-boot catch-up until first resolver cycle ~15m).
2. **split_v2 web** treated orphan `/app/data/*.json` (no Fly volume mount) as authoritative, so `/api/learning/health` read a July-era soul_map tick instead of the worker volume.

## Fix

| Change | Why |
|--------|-----|
| `needs_worker_volume_proxy()` requires a **mounted** volume to stay local | Orphan web JSON no longer disables proxy |
| Proxy `/api/learning/health` (+ `/api/ops/evidence`) to worker | Health reads worker soul_map / schedulers |
| Reorder `check_learning_loop.sh` | `degraded` + alive worker → WARN exit 0 |

## Babysit

```bash
BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh c
APP_BASE_URL=https://subnet-dashboard.fly.dev ./scripts/check_learning_loop.sh
```

Expect: `worker_peer.alive: true`, learning check OK or WARN degraded (not FAIL).
