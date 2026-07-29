# Fly worker split v2 — LOCK

**Status:** **DONE on prod** (2026-07-28) · `worker_peer.alive: true` · GHA learning-loop check green  
**Canon:** `docs/fly-web-worker-split.md` § v2 · `fly.worker-v2.toml` · `split-v2-rollback-runbook.md` (Plan B only)

## Shipped

| PR | What |
|----|------|
| #566 | Prep env-gated |
| #572–#574 | Enable workflow + plumbing |
| #576–#577 | Volume proxy web → worker |
| #578 | `internal/worker_peer.py` HTTP probe |
| #579+ | Worker flycast `[[services]]` + `/api/ops/worker-peer` |
| #581–#584 | Process DNS peer routing, volume repair script |
| #591–#595 | Async/thread peer fetch, `private_ip` URL script |
| #598 | Worker internal HTTP **:8081** (`WORKER_HTTP_PORT=8081`, flycast `:8081`) |
| #599 | `flyctl ips allocate-v6` (no `--yes`) |
| #600–#601 | Learning-loop deploy check + orphan web volume proxy + `/api/learning/health` proxy |

## Prod architecture

- `worker_mode: split_v2` · `web=1 worker=1`
- **Web** (~1GB): HTTP `:8080`, no volume; proxies volume APIs to worker when `needs_worker_volume_proxy()`
- **Worker** (~2GB): owns `data_volume`; background `python -m internal.worker`; uvicorn on **`:8081`**
- Web probes worker: `WORKER_INTERNAL_URL=http://[fdaa:…]:8081` and/or `http://subnet-dashboard.flycast:8081`
- Orphan JSON under `/app/data` on web (no mount) **must not** disable proxy — `data_dir_is_mounted_volume()`

## Babysit

```bash
BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh c
```

Expect `worker_peer.alive: true` (source `http`) on web readiness.

Resolver monitor (post-close-out):

```bash
curl -s "$BASE/api/learning/health" | jq '{status, last_resolver_tick, score_snapshot: .score_snapshot.file_present}'
```

## Do not

- Rollback without `split-v2-rollback-runbook.md` gates + human approve
- Duplicate `worker_peer.py` or second heartbeat PR
- Re-enable `./scripts/fly_enable_worker_v2.sh` — split v2 is live on prod

## Open (not infra-blocked)

- `live_subnets_cache_empty` on readiness (taostats / blockmachine sync)
- Telegram listener `idle_not_started` on worker (`MESSAGE_INTEL_LISTENER=on` in worker entrypoint)
