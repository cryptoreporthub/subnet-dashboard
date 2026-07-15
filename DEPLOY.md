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

### Conviction alert delivery (O1 / §18 A1)

Evaluation (`CONVICTION_ALERTS_ENABLED=on`) creates deduped alerts in the store. **External delivery is off by default** (`CONVICTION_ALERT_DELIVERY` unset → `off`) so CI and cold deploys stay safe.

| `CONVICTION_ALERT_DELIVERY` | Behavior |
|-----------------------------|----------|
| `off` (default) | Evaluate + persist only; no outbound calls |
| `dry_run` | Log would-be deliveries in API response (`delivery.dry_run`) |
| `webhook` | `POST` JSON to `CONVICTION_ALERT_WEBHOOK_URL` |
| `telegram` | `sendMessage` via Bot API |

Optional tuning:

| Variable | Default | Purpose |
|----------|---------|---------|
| `CONVICTION_ALERT_MIN` | `75` | Minimum confidence % to fire |
| `CONVICTION_ALERT_WEBHOOK_URL` | — | Webhook target when `delivery=webhook` |
| `TELEGRAM_BOT_TOKEN` | — | Bot token when `delivery=telegram` |
| `TELEGRAM_ALERT_CHAT_ID` | — | Chat/channel id when `delivery=telegram` |

**Human step — set Fly secrets** (replace placeholders; agent cannot guess tokens):

```bash
# Telegram
flyctl secrets set \
  CONVICTION_ALERT_DELIVERY=telegram \
  TELEGRAM_BOT_TOKEN='<your-bot-token>' \
  TELEGRAM_ALERT_CHAT_ID='<your-chat-id>' \
  --app subnet-dashboard

# Or webhook
flyctl secrets set \
  CONVICTION_ALERT_DELIVERY=webhook \
  CONVICTION_ALERT_WEBHOOK_URL='https://example.com/hooks/alerts' \
  --app subnet-dashboard
```

Redeploy is not required after `flyctl secrets set` — machines restart with new env.

#### Dry-run test (§18 A2)

Safe prod smoke without sending messages:

```bash
flyctl secrets set CONVICTION_ALERT_DELIVERY=dry_run --app subnet-dashboard
curl -fsS -X POST https://subnet-dashboard.fly.dev/api/conviction-alerts/notify | python3 -m json.tool
# Expect delivery.mode=dry_run and delivery.dry_run[] when candidates exist
curl -fsS https://subnet-dashboard.fly.dev/api/conviction-alerts/status | python3 -m json.tool
# Expect delivery_mode: dry_run
```

Revert to live delivery with `telegram` or `webhook` secrets above, or `CONVICTION_ALERT_DELIVERY=off` to disable outbound only.

---

## Environment reference

| Variable | Default | Purpose |
|----------|---------|---------|
| `CALIBRATION_AUTO_RETRAIN` | **on** (fly.toml) | N3 post-resolver retrain hook |
| `CONVICTION_ALERTS_ENABLED` | **on** (fly.toml) | O1 notify evaluation |
| `CONVICTION_ALERT_DELIVERY` | **off** | Outbound delivery: off/dry_run/webhook/telegram |
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
