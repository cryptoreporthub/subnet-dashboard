# Fly web + worker split (Phase B)

**Status:** **v1 in prod** — inline worker subprocess on one machine · **Phase A:** in prod (#332–#333) · **Owner:** infra slice  
**Last updated:** 2026-07-24

## Why

Production runs on a **single Fly machine** (`shared-cpu-1x`, 1GB) that does everything:

- Serves `GET /` + 40+ `/api/*` routes
- Runs resolver, registry sync, live subnet feed, feed warmup on boot
- Absorbs a **hydrate storm** (10–20 parallel API calls per homepage visit)

When the worker saturates, even `/health` stops responding. Phase A (#1) mitigates this on one machine (fast shell, load-shed bypass for light APIs, staggered hydrate, shell cache). **Phase B (#2)** is the structural fix: **split user traffic from background work**.

## Load-separation map

| Phase | List # | What | Status |
|-------|--------|------|--------|
| **A** | 1 | One machine — priority, cache, stagger, load shed | **Now** (#332, #333) |
| **B v1** | 2 | One machine — **web** + **inline worker** subprocess (this doc) | **Now** |
| **B v2** | 2b | Separate worker machine + volume strategy | Deferred |
| C | 3 | Static front (CDN) + API-only Fly | Optional later |
| D | 4 | 2GB RAM or `min_machines_running = 2` | Optional later |
| E | 5 | Microservices split | Not now |

## Target architecture

```
                    ┌─────────────────────────────────────┐
  Browser ────────► │  web process (public HTTP)          │
                    │  uvicorn server:app :8080           │
                    │  • GET /, /health, /static          │
                    │  • Light /api/* (hydrate reads)     │
                    │  • NO resolver / feed boot threads  │
                    └──────────────┬──────────────────────┘
                                   │  same Fly machine + volume
                    ┌──────────────▼──────────────────────┐
                    │  inline worker (sibling OS process) │
                    │  python -m internal.worker          │
                    │  • Resolver scheduler               │
                    │  • Pump ladder + whale warm         │
                    │  • Heartbeat → data/.worker_heartbeat │
                    └─────────────────────────────────────┘
```

**v1 (shipped):** one Fly machine, one `web` process group. `fly_web_entrypoint.sh` forks the worker before `exec uvicorn`. Readiness reports `worker_mode: "split"` and checks `data/.worker_heartbeat`.

**v2 (deferred):** second Fly machine with explicit volume attach strategy — do not scale `worker=1` without that plan.

Same Docker image, two commands. **No second codebase** (single-foundation rule unchanged).

## What runs where

### Web (`RUN_MODE=web` or default)

| Start | Skip |
|-------|------|
| Uvicorn + FastAPI | Resolver scheduler |
| Load-shed middleware | `get_live_subnets` boot thread |
| Homepage shell cache | `warm_subnet_feed` boot thread |
| Read-only access to `data/` + `config/` | Registry background sync (optional — see below) |

Registry **read** stays on web (file-backed). Registry **background write** moves to worker.

### Worker (`RUN_MODE=worker`)

| Start | Skip |
|-------|------|
| Resolver scheduler (`start_prediction_resolver_scheduler`) | HTTP server |
| `start_background_sync` (freshness) | Homepage / static |
| `get_live_subnets` + `warm_subnet_feed` | Load-shed middleware |
| Message-intel listener (if `MESSAGE_INTEL_LISTENER=on`) | |

## Implementation checklist

### 1. `internal/worker.py` (new)

Minimal entrypoint:

```python
# python -m internal.worker
# Blocks forever; starts background schedulers; handles SIGTERM.
```

- Call the same boot functions currently in `server.py` `_lifespan` (resolver, freshness, live subnets, feed warmup).
- No FastAPI app.

### 2. Gate `server.py` lifespan

```python
RUN_MODE = os.environ.get("RUN_MODE", "web").strip().lower()

@asynccontextmanager
async def _lifespan(app: FastAPI):
    if RUN_MODE == "worker":
        yield
        return
    # existing web boot (optionally slimmed — no resolver/feed when worker exists)
    ...
```

Env flag **`BACKGROUND_ON_WEB=off`** (set in fly.toml for web process) skips heavy threads on web even before worker ships.

### 3. `fly.toml` — v1 inline worker (shipped)

```toml
[processes]
  web = "./scripts/fly_web_entrypoint.sh"
  # No separate worker process group — inline subprocess only.

[env]
  RUN_MODE = "web"
  BACKGROUND_ON_WEB = "off"
  INLINE_WORKER = "1"
  ENABLE_INLINE_WORKER = "1"
  WORKER_HEAVY = "essential"
```

`fly_web_entrypoint.sh` spawns `env RUN_MODE=worker python -m internal.worker &` then `exec uvicorn`.

### 3b. `fly.toml` — v2 separate process group (deferred)

Do **not** deploy without volume strategy. Historical outage: `fly scale count worker=1` created a second machine that stole HTTP.

```toml
[processes]
  web = "uvicorn server:app --host 0.0.0.0 --port 8080"
  worker = "python -m internal.worker"
```

### 4. `fly.toml` env per process

```toml
[env]
  RUN_MODE = "web"
  BACKGROUND_ON_WEB = "off"

[processes.worker]
  # flyctl: fly scale count worker=1
  # Set via [env] override or secrets if fly supports per-process env in your flyctl version;
  # fallback: worker cmd sets RUN_MODE=worker inline in processes.worker command.
```

If per-process env is awkward, bake into cmd:

```toml
worker = "env RUN_MODE=worker python -m internal.worker"
```

### 5. Deploy + scale

```bash
# v1: web=1 only; inline worker starts via entrypoint
fly scale count web=1 --app subnet-dashboard
```

**Volume note:** Fly volumes attach to **one machine** at a time. v1 keeps web + worker on that machine so JSON/SQLite state stays consistent without split-brain.

### 6. Tests

- `RUN_MODE=web` + `BACKGROUND_ON_WEB=off` → resolver not started (mock/spy)
- `python -m internal.worker` starts resolver in test with short tick
- Contract test unchanged (`server:app` only)

### 7. Docs / ops

- Update `DEPLOY.md` post-deploy table
- `GET /api/ops/readiness` → report `worker_mode: web|worker|split|combined` and `worker_peer.alive`

## Acceptance criteria

| Check | Pass |
|-------|------|
| `GET /health` | < 2s while homepage + 5 hydrate APIs in flight |
| `GET /` | 200 in < 5s (cached shell) |
| Resolver | Still runs (worker logs / `resolver.running` in readiness) |
| `live_subnets_cache_empty` | Clears within 5 min of worker boot |
| Deploy | Single `fly deploy`; no second app name required for v1 |

## Rollback

- Remove `worker` process from `fly.toml`; set `BACKGROUND_ON_WEB=on` on web.
- Redeploy. Web lifespan resumes starting background threads (current behavior).

## Non-goals (Phase B)

- CDN / static front split (Phase C)
- Second Fly app or microservices
- Redis / queue / external broker
- Changing JSON-on-disk data model

## Related PRs

| PR | Phase | What |
|----|-------|------|
| #328 | A | Fast homepage shell (no pick engine on `GET /`) |
| #329 | A | Boot defer env flags |
| #330 | A | Static above-fold scripts + `api_fetch.js` |
| #332 | A | Load shed + shell cache |
| #333 | A | Load-shed bypass for hydrate APIs |
| TBD | **B** | This doc → implementation PR |

## Next step

v1 shipped. v2 (second machine) only when 1GB inline worker is still CPU-tight and volume attach is designed.
