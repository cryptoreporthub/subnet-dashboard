# Fly worker split v2 — LOCK

**Status:** **ENABLED on prod** · stabilize worker HTTP (#572–#578, #576–#577, this track)  
**Canon:** `docs/fly-web-worker-split.md` § v2 · `fly.worker-v2.toml` · `split-v2-rollback-runbook.md` (Plan B only)

## Shipped

| PR | What |
|----|------|
| #566 | Prep env-gated |
| #572–#574 | Enable workflow + plumbing |
| #576–#577 | Volume proxy web → worker |
| #578 | `internal/worker_peer.py` HTTP probe (`1d2f`) |
| #579+ | Worker flycast `[[services]]` + `/api/ops/worker-peer` |
| #581–#584 | Process DNS peer routing, volume repair script, local fallback |

## Prod

- `worker_mode: split_v2` · `web=1 worker=1`
- Web proxies volume APIs to worker when web has no local volume data
- Web probes worker via `worker.process.subnet-dashboard.internal:8080/api/ops/worker-peer`

## Do not

- Rollback without `split-v2-rollback-runbook.md` gates + human approve
- Duplicate `worker_peer.py` or second heartbeat PR

## Babysit

```bash
BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh c
```

Expect `worker_peer.alive: true` (source `http`) on web readiness.
