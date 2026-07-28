# Deployment Notes

## Fly.io (production)

App: `subnet-dashboard` · region: `sjc` (data_volume lives here) · machine: `shared-cpu-1x` / 1GB

### Deploy

```bash
flyctl deploy --app subnet-dashboard --remote-only --regions sjc --ha=false
```

If CI fails with `insufficient resources to create new machine with existing volume`, prod has **zero machines** (TLS error in browser). The deploy workflow only runs `fly_volume_recover.sh` after repeated deploy failures — not before every deploy.

Recovery (manual or re-run workflow):

```bash
flyctl machines list -a subnet-dashboard          # expect none
flyctl volumes list -a subnet-dashboard           # data_volume in sjc, unattached
./scripts/fly_volume_recover.sh                     # or re-run Fly Deploy workflow
flyctl deploy --app subnet-dashboard --regions sjc --remote-only --ha=false
curl -fsS https://subnet-dashboard.fly.dev/health  # OK
```

Or: [Actions → Fly Deploy → Run workflow](https://github.com/cryptoreporthub/subnet-dashboard/actions/workflows/fly.yml) (after merging deploy-fix PR).

CI (`main` push) runs Deploy Guard then deploys automatically when green.

### Post-deploy verification

| Endpoint | Expected |
|----------|----------|
| `GET /health` | `OK` |
| `GET /api/subnet-integrations` | 200, four primary rows + `connected_count` |
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
| **A** | One machine — fast shell, load shed, hydrate stagger (#332–#333) | troubleshooting above |
| **B v1 (now)** | One machine — **web** (HTTP only) + **inline worker** subprocess on same VM/volume | [`docs/fly-web-worker-split.md`](docs/fly-web-worker-split.md) |

`scripts/fly_web_entrypoint.sh` starts `python -m internal.worker` in the background (nice +10), then `exec uvicorn`. Web has `BACKGROUND_ON_WEB=off`; worker runs pump/resolver/whale warm (`WORKER_HEAVY=essential`).

**VM:** `2gb` on `shared-cpu-1x` — required headroom for inline worker + HTTP on one machine (1GB OOMs/wedges).

**Do not** add a separate `worker` Fly process group or `fly scale count worker=1` without a volume strategy — a second machine steals HTTP with no shared volume.

Verify after deploy:

```bash
curl -s https://subnet-dashboard.fly.dev/api/ops/readiness | jq '{worker_mode, worker_peer, resolver}'
# expect: worker_mode "split", worker_peer.alive true, resolver.running true
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

#### TaoStats on-chain investigation (PR #306)

Required for `/api/investigate/*`, wallet tracing, and SimiVision on-chain chat. Free key: [taostats.io/pro/api-keys](https://taostats.io/pro/api-keys) (Google or GitHub sign-in both work).

```bash
flyctl secrets set TAOSTATS_API_KEY='<your-taostats-api-key>' --app subnet-dashboard
```

Subnet integrations (DeSearch / Chutes / Synth): see [`docs/SUBNET_INTEGRATIONS.md`](docs/SUBNET_INTEGRATIONS.md). Priority: `DESEARCH_API_KEY` (free credits), then `CHUTES_API_KEY` ($10/mo for chat). Skip `SYNTH_API_KEY` unless paying $49/mo.

```bash
flyctl secrets set DESEARCH_API_KEY='...' CHUTES_API_KEY='...' --app subnet-dashboard
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

Live social ingest uses a **Telethon user session** (not the conviction-alert bot). `fly.toml` keeps `MESSAGE_INTEL_LISTENER=off` so CI/cold boots stay safe — enable **`auto`** only after a session file exists on the volume.

**Do not set `WORKER_HEAVY=full` on the current single 2GB Fly machine** — it adds live-subnet sync and wedges HTTP. Telegram runs on the **essential** inline worker (deferred boot; see `internal/background_boot.py`).

| Variable | Required | Purpose |
|----------|----------|---------|
| `TELEGRAM_API_ID` | yes | my.telegram.org app id |
| `TELEGRAM_API_HASH` | yes | my.telegram.org app hash |
| `TELEGRAM_PHONE` | first login | E.164 phone (`+1...`) for one-time auth |
| `TELEGRAM_GROUP` | no | Group username to monitor (default `OfficialSubnetSummer`) |
| `TELEGRAM_SESSION_PATH` | no | Session base path (default `data/telegram_listener` → `/app/data` on Fly) |
| `TELEGRAM_SESSION_STRING` | **preferred** | Telethon `StringSession` from bootstrap — **no Fly SSH** (#541) |
| `MESSAGE_INTEL_LISTENER` | enable | `auto` or `on` after session exists on volume |
| `WORKER_HEAVY` | **essential** | Keep `essential` (default). **`full` is not required** for Telegram and wedges prod. |

**Not the conviction-alert bot:** outbound push uses `TELEGRAM_BOT_TOKEN` + `TELEGRAM_ALERT_CHAT_ID` (see above).

#### Fastest path: session string (no SSH) — paste whole line in one go

Use this when Fly SSH is awkward (phone-only, Windows without curl, iSH, etc.).

1. **On any machine with Python 3.12+** (laptop, Codespaces, friend’s Mac — not required to be Fly):

   ```bash
   cd subnet-dashboard
   source .venv/bin/activate   # or: pip install 'telethon>=1.33.0'
   export TELEGRAM_API_ID='<your-api-id>'
   export TELEGRAM_API_HASH='<your-api-hash>'
   export TELEGRAM_PHONE='+1...'   # E.164, same phone Telegram will text
   python scripts/bootstrap_telegram_session.py
   ```

2. **Telegram texts you a login code** — type it at the prompt (one code, one try; don’t spam retries).

3. **Copy the entire session string** — the script prints one long line between the `---` markers (starts with `1`, no spaces, no line breaks). Select and copy **the whole thing in one go**.

4. **Set Fly secret** — paste that entire string as the value (quotes are fine):

   ```bash
   flyctl secrets set \
     TELEGRAM_SESSION_STRING='PASTE_ENTIRE_LINE_HERE' \
     MESSAGE_INTEL_LISTENER=auto \
     WORKER_HEAVY=essential \
     --app subnet-dashboard
   ```

   Or use [fly.io/apps/subnet-dashboard/secrets](https://fly.io/apps/subnet-dashboard/secrets): name `TELEGRAM_SESSION_STRING`, value = paste the full line in the value field once.

5. **Wait ~2–3 minutes** after the machine restarts, then:

   ```bash
   ./scripts/check_telegram_ready.sh
   ```

   Want: `has_session=true`, `listener.live=true`, `listener.reason=running`.

**FloodWait / lockout:** If bootstrap fails with `FloodWait`, Telegram has rate-limited logins. **Stop** — do not re-run bootstrap or SSH login in a loop. Wait the full time shown (often hours). One OTP attempt per cooldown.

`TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, and `TELEGRAM_PHONE` must already be Fly secrets (or set in the same `flyctl secrets set` command).

#### Fast path when API id/hash are already Fly secrets (SSH)

1. **Bootstrap session on the volume** (one interactive SSH; writes `/app/data/telegram_listener.session`):

   ```bash
   fly ssh console --app subnet-dashboard
   cd /app && python scripts/bootstrap_telegram_session.py
   # Enter the code Telegram sends to your phone. exit when you see OK — session saved.
   ```

2. **Enable listener** (if not already set):

   ```bash
   flyctl secrets set MESSAGE_INTEL_LISTENER=auto WORKER_HEAVY=essential --app subnet-dashboard
   ```

3. **Wait ~2–3 minutes** after machine restart (listener defers ~120s after worker boot).

4. **Verify:**

   ```bash
   ./scripts/check_telegram_ready.sh
   # or: curl -fsS https://subnet-dashboard.fly.dev/api/message-intel/status | python3 -m json.tool
   ```

   Want: `listener.reason=running`, `listener.live=true`, `has_session=true`.

#### Alternative: bootstrap locally, copy session

```bash
export TELEGRAM_API_ID='<your-api-id>'
export TELEGRAM_API_HASH='<your-api-hash>'
export TELEGRAM_PHONE='<your-phone-e164>'
python scripts/bootstrap_telegram_session.py
flyctl ssh sftp shell --app subnet-dashboard
# put data/telegram_listener.session /app/data/telegram_listener.session
```

Then set `MESSAGE_INTEL_LISTENER=auto` and `WORKER_HEAVY=essential` as above.

Optional group override: `TELEGRAM_GROUP='YourGroupUsername'`.

**Security:** never commit `*.session` files or API secrets. Rotate API hash at my.telegram.org if exposed.

#### Mobile-only (no laptop)

You do **not** need a desktop. Session file is created **on the Fly volume** in one SSH session; Telegram sends the login code to the same phone.

1. **Secrets** — [fly.io/apps/subnet-dashboard/secrets](https://fly.io/apps/subnet-dashboard/secrets): `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE` (if not already set).

2. **SSH from phone** — Termux / Blink / a-Shell:
   ```bash
   fly auth login
   fly ssh console --app subnet-dashboard
   cd /app && python scripts/bootstrap_telegram_session.py
   ```

3. **Enable listener** — add `MESSAGE_INTEL_LISTENER=auto` and keep `WORKER_HEAVY=essential` (not `full`).

4. Verify with `./scripts/check_telegram_ready.sh` after ~2–3 minutes.

**No SSH app?** Use `POST /api/message-intel/ingest` from an external forwarder (honest-empty until something ingests).

#### Single-VM stability (learning loop audit 2026-07-27)

On the current **one 2GB machine** (web + inline essential worker), `MESSAGE_INTEL_LISTENER=auto` is safe only when:

- `WORKER_HEAVY=essential` (**never `full`** — #517/#520 wedge),
- Telegram session already exists on the volume,
- Pump / score-snapshot / resolver jobs are staggered (see `internal/heavy_job_gate.py`).
- Score snapshots default to **registry-only** subnet rows on the worker (`SCORE_SNAPSHOT_REGISTRY_ONLY=on`) so the first cycle completes without live-feed wedge; full-universe scoring runs **outside** the heavy-job mutex so resolver can grade while snapshot scores. Day-only scoring on worker (`SCORE_SNAPSHOT_SCORE_HOUR=off` default) halves CPU; resolver boot immediate on worker clears pending after deploy.

If prod flaps (TLS OK but `/health` 0 bytes), **disable Telegram first** (`MESSAGE_INTEL_LISTENER=off`) before scaling VM or splitting processes. Fly **secrets override** `fly.toml` — verify with `flyctl secrets set WRITE_API_TOKEN=…` when ready to lock down write APIs.

### Write API token + metrics (post-audit Phase A)

Optional hardening for mutating routes (`POST /api/message-intel/ingest`, scans, etc.). **Off by default** until the secret is set — CI and local dev unchanged.

```bash
chmod +x scripts/set_write_api_token.sh
./scripts/set_write_api_token.sh                    # generates + flyctl secrets set
# Or: ./scripts/set_write_api_token.sh 'your-token'
```

Clients must send: `Authorization: Bearer <WRITE_API_TOKEN>` on protected writes.

Prometheus metrics: `ENABLE_METRICS=1` in `fly.toml` (default on prod). Verify:

```bash
curl -fsS https://subnet-dashboard.fly.dev/metrics | head
./scripts/babysit_phase.sh a
```

---

## Environment reference

| Variable | Default | Purpose |
|----------|---------|---------|
| `WRITE_API_TOKEN` | unset | Bearer token for mutating API routes (optional) |
| `ENABLE_METRICS` | **1** (fly.toml) | Expose `GET /metrics` (Prometheus) |

| Variable | Default | Purpose |
|----------|---------|---------|
| `CALIBRATION_AUTO_RETRAIN` | **on** (fly.toml) | N3 post-resolver retrain hook |
| `CONVICTION_ALERTS_ENABLED` | **on** (fly.toml) | O1 notify evaluation |
| `CONVICTION_ALERT_DELIVERY` | **off** | Outbound delivery: off/dry_run/webhook/telegram |
| `MESSAGE_INTEL_LISTENER` | **off** (fly.toml) | Telegram ingest at boot (`auto` when session on volume) |
| `WORKER_HEAVY` | **essential** (fly.toml) | Inline worker: pump/resolver + deferred Telegram on `essential`; **`full` wedges 2GB VM** |
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
