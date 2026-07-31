# Fly worker split v2 — LOCK

**Status:** **ROLLED BACK to v1 canon** (2026-07-31)  
**Prod canon:** `fly.toml` · one web machine · `data_volume` + **inline worker** · `WORKER_SPLIT_V2` unset  
**v2:** opt-in only via `scripts/fly_enable_worker_v2.sh` / workflow Enable Worker Split v2  
**Rollback:** `scripts/fly_disable_worker_v2.sh` · `split-v2-rollback-runbook.md`

## Why rolled back

split_v2 put volume APIs behind web→worker private HTTP. On this app that hop stayed unreliable (6PN refused, process DNS refused/NXDOMAIN, flycast flaky). Soft-degraded stubs and local fallthroughs kept the UI from wedging but **did not restore** daily-pick / Telegram / mindmap / learning volume data. Resolver tick age went stale for weeks while CI kept `FORCE_WORKER_SPLIT_V2=1` + `fly.worker-v2.toml` on every main deploy.

## Shipped (historical)

| PR | What |
|----|------|
| #566–#601 | v2 enablement, volume proxy, :8081, peer probes |
| #696–#704 | Proxy resilience / soft degrade / 6PN pin (symptoms only) |
| #705 | Hero/Telegram local fallthrough (defense in depth if v2 returns) |
| **this** | Stop forcing v2 in Fly Deploy; auto-rollback to v1 |

## Prod architecture (canon)

- `worker_mode`: inline / `split` (not `split_v2`)
- **Web** (2GB): HTTP `:8080` + `data_volume` at `/app/data` + inline `python -m internal.worker`
- No web→worker volume proxy required for hero / Telegram / mindmap / learning

## Do not

- Re-add `FORCE_WORKER_SPLIT_V2=1` to `.github/workflows/fly.yml`
- Deploy `fly.worker-v2.toml` from the default Fly Deploy workflow
- Treat soft `status: degraded` stubs as a product fix for missing volume data
- Re-enable v2 without a green web→worker probe soak and human approval

## Re-enable v2 later

1. Prove `scripts/fly_probe_worker_from_web.sh` from a temporary worker scale
2. Human approve
3. `./scripts/fly_enable_worker_v2.sh` or workflow **Enable Worker Split v2**
