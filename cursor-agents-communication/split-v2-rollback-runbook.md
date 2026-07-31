# Split v2 rollback runbook

**Canon (2026-07-31):** production runs **v1** — one web machine, `data_volume` + inline worker (`fly.toml`).

split_v2 (dedicated worker + web→worker volume proxy) is **opt-in only**. It left hero / Telegram / mindmap / learning stuck whenever private HTTP failed. Soft stubs and proxy fallthroughs are not a substitute for co-located volume.

## When to roll back

Any of:

- `worker_mode: split_v2` and `worker_peer.alive: false` / `worker_http_unreachable`
- Volume APIs return soft `status: degraded` for >10 min after worker restart
- Learning loop stalled (resolver tick age days/weeks)
- Repeated proxy PRs without restoring real volume payloads

## Preferred path (GitHub Actions)

1. Merge a main deploy that uses `fly.toml` (no `FORCE_WORKER_SPLIT_V2`) — deploy workflow auto-detects v2 and runs `scripts/fly_disable_worker_v2.sh`.
2. Or run workflow **Disable Worker Split v2** with confirm input `disable`.

## Manual path (`flyctl`)

```bash
chmod +x scripts/fly_disable_worker_v2.sh
./scripts/fly_disable_worker_v2.sh

# Verify — expect worker_mode NOT split_v2; inline peer alive after warm
curl -s https://subnet-dashboard.fly.dev/api/ops/readiness | jq '{worker_mode, worker_peer, issues}'
curl -s https://subnet-dashboard.fly.dev/api/daily-pick | jq '{status, action, pick: (.pick!=null)}'
curl -s 'https://subnet-dashboard.fly.dev/api/message-intel?limit=2' | jq '{status, n: (.messages|length), empty}'
```

**Important:** `fly secrets unset WORKER_SPLIT_V2` — do not only set `=off`. The deploy guard treats **secret presence** as v2.

## Re-enable Telegram after rollback

```bash
# Only after telegram session exists on the volume
fly secrets set MESSAGE_INTEL_LISTENER=auto --app subnet-dashboard
```

## Re-enable v2 later (opt-in)

Only after private HTTP is proven (probe from web machine succeeds for 24h):

```bash
# workflow: Enable Worker Split v2 (confirm=enable)
# or:
./scripts/fly_enable_worker_v2.sh
```

See `cursor-agents-communication/fly-worker-split-v2-lock.md` and `DEPLOY.md`.
