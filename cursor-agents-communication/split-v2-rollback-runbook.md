# Split v2 rollback runbook (Plan B only)

**Default:** stay on `split_v2` with volume proxy (#576/#577) and cross-machine HTTP heartbeat.

**Do not run this** unless:
1. Worker machine is scaled (`worker=1`) and warmed up (~5 min after boot), and
2. `fly logs -p worker` still shows listener/resolver dead, and
3. Human approves rollback.

## Symptoms that justify rollback

- `worker_peer.alive: false` with `note: worker_http_unreachable` for >10 min after worker restart
- `/api/message-intel/status` returns 503 consistently (worker proxy down)
- Learning loop stalled >2h with no resolver ticks after worker warm-up
- Repeated VM wedge (503/timeout on `/health`) that restart does not fix

## Rollback steps (v1 inline worker)

```bash
# 1. Scale dedicated worker to zero
fly scale count worker=0 --app subnet-dashboard

# 2. Disable v2 split — restores inline worker on web machine
fly secrets set WORKER_SPLIT_V2=off --app subnet-dashboard

# 3. Redeploy (or restart web machine)
fly apps restart subnet-dashboard

# 4. Verify v1 inline worker
curl -s https://subnet-dashboard.fly.dev/api/ops/readiness | jq '{worker_mode, worker_peer, issues}'
# expect: worker_mode "split", worker_peer.alive true, peer "inline_worker"
```

## Re-enable listener after rollback

```bash
fly secrets set MESSAGE_INTEL_LISTENER=auto --app subnet-dashboard
```

## Re-enable v2 later

See `DEPLOY.md` § Worker split v2 and `cursor-agents-communication/fly-worker-split-v2-lock.md`.

```bash
fly scale count web=1 worker=1 --app subnet-dashboard
fly secrets set WORKER_SPLIT_V2=on --app subnet-dashboard
```

Babysit: `BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh c`
