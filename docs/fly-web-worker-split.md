# Fly web + worker split (Phase B)

**Status:** planned · **Phase A:** in prod (#332–#333) · **Owner:** infra slice  
**Last updated:** 2026-07-18

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
| **B** | 2 | Two processes — **web** + **worker** (this doc) | Planned |
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
                                   │
                    shared volume  │  data_volume → /app/data
                    (soul_map,    │  (predictions, picks, SQLite)
                     predictions)  │
                                   │
                    ┌──────────────▼──────────────────────┐
                    │  worker process (no public HTTP)    │
                    │  python -m internal.worker          │
                    │  • Resolver scheduler             │
                    │  • Registry freshness sync        │
                    │  • Live subnets + feed warmup     │
                    │  • Optional message-intel listener  │
                    └─────────────────────────────────────┘
```

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

### 3. `fly.toml` — process groups

Fly Machines support multiple processes in one app (same image, different `cmd`):

```toml
[processes]
  web = "uvicorn server:app --host 0.0.0.0 --port 8080"
  worker = "python -m internal.worker"

[[services]]
  processes = ["web"]
  # ... existing http_service checks on /health ...

# worker: no [[services]] — not on public edge
```

Both processes mount `data_volume` → `/app/data`.

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
# After first deploy with [processes]:
fly scale count web=1 worker=1 --app subnet-dashboard
fly volumes list  # confirm data_volume attached to BOTH machines (or shared — see risks)
```

**Volume note:** Fly volumes attach to **one machine** at a time. Options:

| Approach | Pros | Cons |
|----------|------|------|
| **A. Worker only on same machine as web** | One volume, no split-brain | Less isolation (still share CPU/RAM) |
| **B. Worker on second machine + same region volume** | Real CPU isolation | Need volume attach strategy or accept worker reads via API |
| **C. Worker machine with volume; web machine stateless reads via SQLite WAL / API** | Best isolation | More work |

**Recommended for v1:** **two processes on one machine** (Fly `[[vm]]` with process groups) — gets thread/GIL separation for HTTP vs schedulers without volume complexity. **v2:** second machine when CPU is still tight.

### 6. Tests

- `RUN_MODE=web` + `BACKGROUND_ON_WEB=off` → resolver not started (mock/spy)
- `python -m internal.worker` starts resolver in test with short tick
- Contract test unchanged (`server:app` only)

### 7. Docs / ops

- Update `DEPLOY.md` post-deploy table
- `GET /api/ops/readiness` → report `worker_mode: web|worker|combined`

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

Open implementation PR: `internal/worker.py` + `RUN_MODE` gate + `fly.toml` `[processes]` (web + worker on one machine first).
