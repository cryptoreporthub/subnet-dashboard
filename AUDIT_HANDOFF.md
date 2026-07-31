# Audit handoff (2026-07-31)

**Repo tip:** `main` @ `181eb80` (#708)  
**Live:** `https://subnet-dashboard.fly.dev`  
**Product:** FastAPI Subnet Dashboard + SimiVision (Bittensor subnet analytics / council)

## What Claude should audit (prefer **repo**, not live-first)

**Primary: repository architecture + ops truth**

1. **Canon deploy path** — `.github/workflows/fly.yml` must deploy `fly.toml` (v1). Must **not** set `FORCE_WORKER_SPLIT_V2=1` or default to `fly.worker-v2.toml`.
2. **Worker split history** — `docs/fly-web-worker-split.md`, `cursor-agents-communication/fly-worker-split-v2-lock.md`, `split-v2-rollback-runbook.md`.
3. **Proxy leftovers** — `internal/worker_proxy.py` + middleware still exist for opt-in v2; soft-degraded stubs are defense, not product.
4. **Single-foundation** — one `server:app`; no Flask / second server package.
5. **Contract guard** — `tests/test_endpoint_contract.py` (Fly Deploy Gate).
6. **Known debt** — many tests still reference `server_original` / unported slices (see `AGENTS.md`).

**Secondary: live site smoke** (product reality; flaky under load)

```bash
curl -sS -m 15 https://subnet-dashboard.fly.dev/health
curl -sS -m 20 https://subnet-dashboard.fly.dev/api/ops/live | jq '{worker_mode,worker_peer,volume}'
curl -sS -m 20 https://subnet-dashboard.fly.dev/api/daily-pick | jq '{status,action,pick:(.pick!=null)}'
curl -sS -m 20 'https://subnet-dashboard.fly.dev/api/message-intel?limit=2' | jq '{status,empty,total:(.meta.total_messages)}'
```

Expect after healthy boot: `worker_mode` = `split` (inline), peer `inline_worker` alive — **not** `split_v2`.

## Timeline (so the “we switched twice” story is clear)

| Phase | Intent | Outcome |
|-------|--------|---------|
| **v1** | One machine: HTTP + volume + inline worker | Worked for data; could **wedge** `/health` under boot/hydrate load |
| **v2** | Separate worker owns volume; web proxies volume APIs | Aimed to stop wedges; **private web→worker HTTP** stayed unreliable → hero/Telegram/mindmap/learning soft-degraded for weeks |
| **Rollback (#706–#708)** | Co-locate volume again; stop CI forcing v2 | Data path works again; **single-machine wedge risk returns** (mitigate with boot defer / skip homepage warm / tighter health checks) |

**Do not re-enable v2** without a proven web→worker probe soak + human approve.

## What “good” looks like for launch

- Homepage and core APIs respond without eternal “Loading desk…” / soft `status: degraded` on volume routes
- Learning loop ticks on the volume (`/api/learning/health`)
- Telegram desk shows real `message-intel` totals when session/listener configured
- Daily pick is honest HOLD/pending or a real pick — not `worker_unreachable` stubs

## Out of scope / noise for this audit

- Stale open draft PRs (#692, #686, #675, …) — ignore unless asked
- Runtime `data/*.json` / `.venv` churn in a local checkout — not source of truth; Fly volume is
- Soft-proxy PRs #698–#705 — historical symptom treatment; #705 left closed/superseded after v1 rollback

## Suggested audit questions for Claude

1. Is v1 the right long-term architecture, or should v2 be rebuilt with a proven private network (or shared volume strategy)?
2. Where do homepage / mindmap / pump still block the event loop on one 2GB VM?
3. What is the smallest hardening path so deploys cannot wedge for >2 minutes?
4. Which volume APIs still assume split_v2 proxy semantics incorrectly?
