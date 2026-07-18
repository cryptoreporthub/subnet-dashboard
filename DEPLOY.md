# Deployment Notes

## Fly.io (production)

App: `subnet-dashboard` · region: `sjc` (data_volume lives here) · machine: `shared-cpu-1x` / 1GB

### Deploy

```bash
flyctl deploy --app subnet-dashboard --remote-only
```

CI (`main` push) runs Deploy Guard (contract tests + static checks) then deploys automatically when green.

### Post-deploy verification

| Endpoint | Expected |
|----------|----------|
| `GET /health` | `OK` |
| `GET /api/data-freshness` | 200, `stale` + `effective_source` fields |
| `GET /api/ops/readiness` | 200, `ready`, `issues`, resolver + feed probes |
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

### Production looks thin (troubleshooting)

Symptom: homepage feels empty, trust banner shows STALE, or daily pick is HOLD with no published LONG.

**This is often honest product state, not a deploy failure.** Check one endpoint:

```bash
curl -fsS https://subnet-dashboard.fly.dev/api/ops/readiness | python3 -m json.tool
```

| Signal | Healthy | Thin but honest | Ops action |
|--------|---------|-----------------|------------|
| `learning.graded` | > 0 | 0 | Volume missing — confirm Fly `data_volume` mount at `/app/data` |
| `resolver.running` | true | false | Resolver should boot in `server.py` lifespan; check `GET /api/predictions/resolver` |
| `subnet_feed.effective_source` | blockmachine or taomarketcap | registry | Wait for blockmachine sync (~5 min) or TMC cache; machine needs 1GB (`fly.toml`) |
| `daily_pick.action` | LONG + published | HOLD + candidate | Audit gate blocked pick — not a feed outage |
| `taostats.configured` | true | false | `flyctl secrets set TAOSTATS_API_KEY=...` (investigation + richer names) |

`/api/data-freshness` reports the **blockmachine cache file** (`data/live_subnets.json`). `/api/ops/readiness` also reports the **effective feed** (TMC SQLite cache + registry) so STALE badge + working subnets can coexist during warm-up.

If `GET /api/subnets` times out, the app falls back to registry after `SUBNETS_LOAD_TIMEOUT_SECONDS` (default 12). Boot also runs a background subnet-feed warmup thread (deferred `BOOT_DEFER_SECONDS`, default 45).

### Load separation (Phase A → B)

| Phase | What | Doc |
|-------|------|-----|
| **A (now)** | One machine — fast shell, load shed, hydrate stagger (#332–#333) | troubleshooting above |
| **B (now)** | Colocated worker subprocess — background off HTTP path (Dockerfile CMD) | [`docs/fly-web-worker-split.md`](docs/fly-web-worker-split.md) |

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

#### TaoStats on-chain investigation (PR #306)

Required for `/api/investigate/*`, wallet tracing, and SimiVision on-chain chat. Free key: [taostats.io/pro/api-keys](https://taostats.io/pro/api-keys) (Google or GitHub sign-in both work).

```bash
flyctl secrets set TAOSTATS_API_KEY='<your-taostats-api-key>' --app subnet-dashboard
```

Verify:

```bash
curl -fsS 'https://subnet-dashboard.fly.dev/api/investigate/subnet/82/sellers?limit=5' | python3 -m json.tool
# Expect "status": "success" (not "unavailable")
```

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

### Message-intel Telegram listener (§18 C1)

Live social ingest uses **Telethon user session** (not the conviction-alert bot). `fly.toml` keeps `MESSAGE_INTEL_LISTENER=off` by default so CI/cold boots stay safe — enable only after a session file exists on the volume.

| Variable | Required | Purpose |
|----------|----------|---------|
| `TELEGRAM_API_ID` | yes | my.telegram.org app id |
| `TELEGRAM_API_HASH` | yes | my.telegram.org app hash |
| `TELEGRAM_PHONE` | first login | E.164 phone (`+1...`) for one-time auth |
| `TELEGRAM_GROUP` | no | Group username to monitor (default `OfficialSubnetSummer`) |
| `TELEGRAM_SESSION_PATH` | no | Session base path (default `data/telegram_listener` → `/app/data` on Fly) |
| `MESSAGE_INTEL_LISTENER` | enable | Set `auto` or `on` to start listener at boot |

**Step 1 — bootstrap session locally** (interactive SMS/Telegram code; not runnable headless on Fly):

```bash
export TELEGRAM_API_ID='<your-api-id>'
export TELEGRAM_API_HASH='<your-api-hash>'
export TELEGRAM_PHONE='<your-phone-e164>'
python scripts/bootstrap_telegram_session.py
# Creates data/telegram_listener.session (+ .session-journal while open)
```

**Step 2 — copy session to Fly volume** (human / `flyctl ssh`):

```bash
flyctl ssh console --app subnet-dashboard
# From local machine in another terminal:
flyctl ssh sftp shell --app subnet-dashboard
# put data/telegram_listener.session /app/data/telegram_listener.session
```

**Step 3 — set Fly secrets and enable listener:**

```bash
flyctl secrets set \
  TELEGRAM_API_ID='<your-api-id>' \
  TELEGRAM_API_HASH='<your-api-hash>' \
  TELEGRAM_PHONE='<your-phone-e164>' \
  MESSAGE_INTEL_LISTENER=auto \
  --app subnet-dashboard
```

Optional group override: `TELEGRAM_GROUP='YourGroupUsername'`.

Verify:

```bash
curl -fsS https://subnet-dashboard.fly.dev/api/message-intel/status | python3 -m json.tool
# listener.reason=running, listener.live=true when session + group resolve
./scripts/verify_prod.sh
```

**Security:** never commit `*.session` files or API secrets. Rotate API hash at my.telegram.org if exposed.

#### Mobile-only (no laptop)

You do **not** need a desktop. Session file is created **on the Fly volume** in one SSH session; Telegram sends the login code to the same phone.

1. **Secrets in browser** — [fly.io/apps/subnet-dashboard/secrets](https://fly.io/apps/subnet-dashboard/secrets)  
   Add (do **not** enable listener yet):
   - `TELEGRAM_API_ID` = your api id  
   - `TELEGRAM_API_HASH` = your api hash  
   - `TELEGRAM_PHONE` = E.164, e.g. `+14155551234`  
   Leave `MESSAGE_INTEL_LISTENER` unset or `off` for now.

2. **SSH from phone** — install `flyctl` once (Android: [Termux](https://termux.dev); iOS: [Blink](https://blink.sh) or [a-Shell](https://holzschu.github.io/a-Shell-docs/)), then:
   ```bash
   fly auth login   # opens browser on phone
   fly ssh console --app subnet-dashboard
   ```

3. **Bootstrap inside the machine** (session writes to `/app/data` automatically):
   ```bash
   cd /app
   python scripts/bootstrap_telegram_session.py
   ```
   When prompted, enter the code Telegram sends to your app. Type `exit` when you see `OK — session saved`.

4. **Enable listener** — back in [Fly secrets](https://fly.io/apps/subnet-dashboard/secrets), add:
   - `MESSAGE_INTEL_LISTENER` = `auto`  
   Machine restarts; listener should show `running` at `/api/message-intel/status`.

**No SSH app?** Skip live listener for now — `POST /api/message-intel/ingest` still accepts pushed messages (honest-empty until something ingests).

---

## Environment reference

| Variable | Default | Purpose |
|----------|---------|---------|
| `CALIBRATION_AUTO_RETRAIN` | **on** (fly.toml) | N3 post-resolver retrain hook |
| `CONVICTION_ALERTS_ENABLED` | **on** (fly.toml) | O1 notify evaluation |
| `CONVICTION_ALERT_DELIVERY` | **off** | Outbound delivery: off/dry_run/webhook/telegram |
| `MESSAGE_INTEL_LISTENER` | **off** (fly.toml) | Telegram ingest at boot (`auto`/`on` when session ready) |
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
