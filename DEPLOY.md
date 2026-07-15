# Deployment Notes

## Fly.io (production)

App: `subnet-dashboard` · region: `sea` · machine: `shared-cpu-1x` / 1GB

### Deploy

```bash
flyctl deploy --app subnet-dashboard --remote-only
```

CI (`main` push) runs Deploy Guard (contract tests + static checks) then deploys automatically when green.

### Post-deploy verification

| Endpoint | Expected |
|----------|----------|
| `GET /health` | `OK` |
| `GET /api/data-freshness` | 200, `is_stale` fields |
| `GET /api/calibration/status` | 200, weights + thresholds |
| `GET /api/conviction-alerts/status` | 200, `enabled: true` (after Phase P) |
| `GET /api/signal-hub/status` | 200 |

### Persistent data

Runtime state lives on the Fly volume `data_volume` → `/app/data` (`soul_map.json`, predictions, SQLite). **Do not** create a second volume without human `flyctl` access.

---

### Automated check

```bash
./scripts/verify_prod.sh
# or: APP_BASE_URL=https://subnet-dashboard.fly.dev ./scripts/verify_prod.sh
```

---

## Custom domain + CDN (O4 / P4)

**Recommended hostname:** `dashboard.cryptoreporthub.com` → `subnet-dashboard.fly.dev`

`ALLOWED_ORIGINS` is prewired in `fly.toml` for fly.dev + cryptoreporthub.com. After DNS propagates, run (requires `flyctl auth login`):

```bash
flyctl certs add dashboard.cryptoreporthub.com --app subnet-dashboard
```

Fly prints DNS records. At your registrar:

| Record | Target |
|--------|--------|
| `CNAME dashboard` | `subnet-dashboard.fly.dev` |

Wait until `flyctl certs show dashboard.cryptoreporthub.com` reports **Ready**, then verify:

```bash
curl -fsS https://dashboard.cryptoreporthub.com/health
```

Human steps — the agent cannot access your registrar or Fly account without credentials.

**Quick checklist:** `./scripts/f7-custom-domain.sh`

### CDN for static assets (recommended)

Put **Cloudflare** (or similar) in front of the custom domain:

1. Add site → proxy orange-cloud ON.
2. **SSL/TLS** → Full (strict).
3. **Caching** → Cache Rules:
   - `/static/*` → Edge TTL 1 day, Browser TTL 1 hour
   - `/api/*` → Bypass cache
   - `/` → Bypass cache (HTML is dynamic)
4. **Page Rules** (legacy) or Cache Rules: never cache `POST` requests.

The app sets `Cache-Control: public, max-age=3600` on `/static/*` and 30s on `/api/registry`, `/api/summary`, `/api/stats`. CDN should **not** cache `POST` routes.

`ALLOWED_ORIGINS` is already in `fly.toml`; override only if you add more hostnames:

```bash
flyctl secrets set ALLOWED_ORIGINS="https://dashboard.cryptoreporthub.com,https://subnet-dashboard.fly.dev" --app subnet-dashboard
```

### Production flags (Phase P — on by default in fly.toml)

```bash
# N3 — auto-retrain after resolver when ≥30 new resolved rows since last retrain
flyctl secrets set CALIBRATION_AUTO_RETRAIN=on --app subnet-dashboard

# O1 — conviction-threshold alerts (uses existing AlertEngine store)
flyctl secrets set CONVICTION_ALERTS_ENABLED=on --app subnet-dashboard
```

Both default **on** in `fly.toml` after Phase P merge. Override via `flyctl secrets set` if needed.

---

## Environment reference

| Variable | Default | Purpose |
|----------|---------|---------|
| `CALIBRATION_AUTO_RETRAIN` | **on** (fly.toml) | N3 post-resolver retrain hook |
| `CONVICTION_ALERTS_ENABLED` | **on** (fly.toml) | O1 notify evaluation |
| `ALLOWED_ORIGINS` | fly.dev + cryptoreporthub.com | CORS allowlist |

---

## Version history

### 3.4.0 (Phase N/O)
- N2 scenario outcome backfill on `/api/scenario-memory`
- N3 env-gated calibration auto-retrain post-resolver
- O1 `/api/conviction-alerts/*` (distinct from Phase L `/api/alerts`)
- O4 custom domain + CDN documentation

### 3.3.1
- Technical indicators on mindmap summary
- `/api/rotation-tokens`
- Learning loop feedback collection
