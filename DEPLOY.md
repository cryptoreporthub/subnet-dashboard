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
| `GET /api/conviction-alerts/status` | 200, `enabled: false` by default |
| `GET /api/signal-hub/status` | 200 |

### Persistent data

Runtime state lives on the Fly volume `data_volume` → `/app/data` (`soul_map.json`, predictions, SQLite). **Do not** create a second volume without human `flyctl` access.

---

## Custom domain + CDN (O4)

Human steps — the agent documents; DNS is done in your registrar / CDN dashboard.

### 1. Add custom hostname on Fly

```bash
flyctl certs add dashboard.yourdomain.com --app subnet-dashboard
```

Fly prints the required DNS records (CNAME or A/AAAA). Wait until `flyctl certs show` reports **Ready**.

### 2. Point DNS

| Record | Target |
|--------|--------|
| `CNAME dashboard` | `subnet-dashboard.fly.dev` |

Or use Fly’s anycast IPs if you prefer A/AAAA (see `flyctl ips list`).

### 3. CDN for static assets (recommended)

Put **Cloudflare** (or similar) in front of the custom domain:

1. Add site → proxy orange-cloud ON.
2. **SSL/TLS** → Full (strict).
3. **Caching** → Cache Rules:
   - `/static/*` → Edge TTL 1 day, Browser TTL 1 hour
   - `/api/*` → Bypass cache
   - `/` → Bypass cache (HTML is dynamic)
4. **Page Rules** (legacy) or Cache Rules: never cache `POST` requests.

The app already sets short `Cache-Control` on `/api/registry`, `/api/summary`, `/api/stats` (30s). CDN should **not** cache authenticated or `POST` routes.

### 4. Update Fly env after domain cutover

```bash
flyctl secrets set ALLOWED_ORIGINS="https://dashboard.yourdomain.com,https://subnet-dashboard.fly.dev" --app subnet-dashboard
```

Redeploy so CORS middleware picks up the new origin.

### 5. Production flags

**Default on prod** (committed in `fly.toml` since Phase P):

- `CALIBRATION_AUTO_RETRAIN=on` — auto-retrain after resolver when ≥30 new resolved rows
- `CONVICTION_ALERTS_ENABLED=on` — conviction-threshold alerts via `AlertEngine`

To disable without redeploy:

```bash
flyctl secrets set CALIBRATION_AUTO_RETRAIN=off CONVICTION_ALERTS_ENABLED=off --app subnet-dashboard
```

---

## Environment reference

| Variable | Default | Purpose |
|----------|---------|---------|
| `CALIBRATION_AUTO_RETRAIN` | **on** (Phase P) | N3 post-resolver retrain hook |
| `CALIBRATION_AUTO_RETRAIN_MIN_NEW` | 30 | Min new resolutions since last retrain |
| `CALIBRATION_ADMIN_TOKEN` | unset | Guards `POST /api/calibration/retrain` |
| `CONVICTION_ALERTS_ENABLED` | **on** (Phase P) | O1 notify evaluation |
| `CONVICTION_ALERT_MIN` | 75 | Min confidence % for alerts (cyan tier) |
| `RESOLVER_REFRESH_MINUTES` | 15 | Prediction resolver cadence |
| `ALLOWED_ORIGINS` | `https://subnet-dashboard.fly.dev` | CORS allowlist |

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
