# Sentry Telemetry Findings

**Directive:** Sentry Telemetry Review v1.1  
**Evidence tiers:** Confirmed from code | Confirmed from tests | Confirmed locally at runtime | Confirmed in production | Confirmed in production via MCP | Historical evidence | Unavailable/pending

---

## Phase boundary — Wave 1 (2026-08-24)

**Scope:** Read-only inspection, local mock tests, Browser SDK discovery. No Fly secret changes, no `main` push.

### Confirmed

| Item | Tier |
|------|------|
| No collision with Intel Loop PR #1034 (`95f7e0c4`) on `internal/sentry_setup.py` | Confirmed from code + VCS history |
| FastAPI/Starlette integrations auto-enable with SDK 2.19.0 + current init | Confirmed locally at runtime |
| Local route capture (mock): `/subnetsummer`, `/api/pump-alerts`, worker warnings | Confirmed locally at runtime |
| ~423 `logger.warning` call sites — quota **risk estimate**, not measured volume | Confirmed from code |
| Browser SDK not installed; static JS + CSP documented | Confirmed from code |
| No `SENTRY_RELEASE` in Dockerfile / fly.yml | Confirmed from code |

### Unavailable/pending (Wave 1)

- Sentry MCP (needsAuth)
- Fly secret names (flyctl not on VM initially)
- Production event arrival

**Saga (Wave 1):** Local mechanism verified; production capture pending.

---

## Phase boundary — Wave 2 partial (2026-08-24)

**Scope:** Fly secret configuration, production send verification, prod route smoke. No Path B code changes. Sentry MCP still blocked.

### Actions performed

| Action | Tier | Notes |
|--------|------|-------|
| `SENTRY_DSN` + `SENTRY_ENVIRONMENT=production` set on Fly | Confirmed in production | Machine rolled; healthy |
| Local send test | Confirmed locally at runtime | `init_active=True`; event ID returned (not repeated here) |
| Prod send via `fly machine exec` | Confirmed in production | `init True`; prod verify message event ID returned |
| Prod `SENTRY_ENVIRONMENT=production` on machine | Confirmed in production | `FLY_APP_NAME=subnet-dashboard` also present |
| `/health`, `/api/pump-alerts`, `/subnetsummer` | Confirmed in production | All HTTP 200; pump `status=empty` |
| `.cursor/mcp.json` Sentry URL added | Confirmed from code | Branch `cursor/sentry-mcp-config-72e0`; not on `main` |

### Event arrival (Wave 2)

- **Confirmed in production:** Sentry SDK initializes on Fly machine with deployed secrets; `capture_message` returns event IDs (transport path works).
- **Unavailable/pending:** Sentry UI / MCP confirmation of issues list, grouping, tags, and volume (MCP needs Desktop OAuth).

### Saga gate (amended P1)

- **Confirmed locally at runtime (Wave 1):** Mock route failures attach request URLs.
- **Confirmed in production:** Routes healthy; no natural failure events observed post-restart.
- **Status:** *Transport and initialization verified in production; saga-relevant route capture remains pending for production failure/natural events.*

### P3 quota/tier gate

**Unavailable/pending** until Sentry MCP or dashboard access. Risk estimate from Wave 1 still applies.

### Alert rules

**Not activated.** Design prepared in Wave 1. Activation requires MCP/dashboard grouping inspection.

### Unavailable/pending (Wave 2)

1. Sentry MCP OAuth (Cursor Desktop — Settings → MCP → sentry → Connect)
2. Issue search, grouping, volume counts, release metadata in Sentry UI via agent
3. `SENTRY_RELEASE` (not configured on Fly or image)
4. Path B baseline (not approved)

---

## Phase boundary — Wave 2 MCP-confirmed (2026-08-24)

**Scope:** Sentry MCP read-only probe, alert-rule design, verify-issue cleanup. No Path B code changes, no Fly secrets/deploy.

### MCP authentication

| Check | Tier | Result |
|-------|------|--------|
| Sentry MCP `whoami` | Confirmed in production via MCP | User **Cryptonic** (`cryptoreporthub@gmail.com`, id 4912988) |
| `find_organizations` | Confirmed in production via MCP | Org **simivision** → [simivision.sentry.io](https://simivision.sentry.io), region `https://us.sentry.io` |
| `find_projects` | Confirmed in production via MCP | Project **python-fastapi** (sole project) |

### Production issue inventory (MCP, last 7d, `environment:production`)

**Dashboard:** [Issues — production](https://simivision.sentry.io/issues/?query=environment%3Aproduction)

| Issue | Events (7d) | Events (24h) | Culprit / source | Level | Release tag |
|-------|-----------|--------------|------------------|-------|-------------|
| [PYTHON-FASTAPI-5](https://simivision.sentry.io/issues/PYTHON-FASTAPI-5) | 20 | 20 | `fetchers.taostats_client` / worker | warning | **none** |
| [PYTHON-FASTAPI-4](https://simivision.sentry.io/issues/PYTHON-FASTAPI-4) | 4 | 4 | `internal.council.resolver` / worker | warning | **none** |
| [PYTHON-FASTAPI-6](https://simivision.sentry.io/issues/PYTHON-FASTAPI-6) | 4 | 4 | `/api/daily-pick` (GET) | warning | **none** |
| [PYTHON-FASTAPI-3](https://simivision.sentry.io/issues/PYTHON-FASTAPI-3) | 3 | 3 | worker (learning metrics timeout) | warning | **none** |
| [PYTHON-FASTAPI-2](https://simivision.sentry.io/issues/PYTHON-FASTAPI-2) | 3 | 3 | worker (homepage cache warm) | warning | **none** |
| [PYTHON-FASTAPI-7](https://simivision.sentry.io/issues/PYTHON-FASTAPI-7) | 2 | 2 | worker (resolver cycle timeout) | warning | **none** |
| [PYTHON-FASTAPI-A](https://simivision.sentry.io/issues/PYTHON-FASTAPI-A) | 1 | 1 | worker (loop stall guard revive) | warning | **none** |
| [PYTHON-FASTAPI-9](https://simivision.sentry.io/issues/PYTHON-FASTAPI-9) | 1 | 1 | worker (loop stall guard stale snapshot) | warning | **none** |
| [PYTHON-FASTAPI-8](https://simivision.sentry.io/issues/PYTHON-FASTAPI-8) | 1 | 1 | prod verify message (resolved) | info | **none** |

**Aggregate volume (MCP `search_events`):**

| Window | Total production events |
|--------|-------------------------|
| 24h | **39** |
| 7d | **41** |

**Discover aggregate:** [24h count by issue](https://simivision.sentry.io/explore/discover/homepage/?dataset=errors&queryDataset=error-events&query=environment%3Aproduction&field=issue&field=count%28%29&sort=-count%28%29&statsPeriod=24h&mode=aggregate&yAxis=count%28%29)

**Grouping observations:**

- Issues group cleanly by logger message / route (TaoStats 404, cold-cache ratio, daily-pick timeout, resolver timeout, loop-stall guard).
- Production events carry `environment:production`, `server_name` (Fly machine), runtime tags — **no `release` tag** on any production event.
- Local verify ([PYTHON-FASTAPI-1](https://simivision.sentry.io/issues/PYTHON-FASTAPI-1)) had `environment:development` and `release: 95f7e0c4…` (git SHA from local env, not Fly image).

### Verify issues (resolved as test noise)

| Issue | Tier | Action |
|-------|------|--------|
| PYTHON-FASTAPI-1 (`sentry-agent-verify-local`) | Confirmed in production via MCP | **Resolved** — intentional local transport test |
| PYTHON-FASTAPI-8 (`prod-agent-verify-wave2`) | Confirmed in production via MCP | **Resolved** — intentional prod transport test |

### Saga gate (P1 amended)

| Route / path | Prod/natural Sentry events? | Tier |
|--------------|----------------------------|------|
| `/subnetsummer` | **No** | Confirmed in production via MCP |
| `/api/pump-alerts` | **No** | Confirmed in production via MCP |
| `/api/daily-pick` | Yes — [PYTHON-FASTAPI-6](https://simivision.sentry.io/issues/PYTHON-FASTAPI-6) (timeout warnings, 4 events) | Confirmed in production via MCP |
| listener / message-intel | **No** | Confirmed in production via MCP |

**Status:** *Transport and initialization verified in production; saga-relevant route capture remains pending for `/subnetsummer` and `/api/pump-alerts` (no production or natural failure events observed).*

Wave 1 local mock capture for `/subnetsummer` and `/api/pump-alerts` remains **Confirmed locally at runtime** only.

### P3 quota / tier gate

| Item | Tier | Notes |
|------|------|-------|
| Observed production volume | Confirmed in production via MCP | 39 events / 24h, 41 / 7d (all since transport went live ~1h window) |
| TaoStats storm risk | Confirmed in production via MCP | PYTHON-FASTAPI-5 alone = **20/39 (51%)** of 24h volume; worker-side, recurring |
| Code risk estimate (~423 `logger.warning` sites) | Confirmed from code | Still a ceiling, not measured — but prod already shows warning-level ingest at scale |
| Sentry plan/tier/quota limits | **Unavailable/pending** | No MCP tool exposes org billing/quota; manual dashboard check required |

**Storm assessment:** At current rates (~20 TaoStats warnings/hour from one worker loop), alerting on all `level:warning` production events would fatigue quickly. Path B should add logger-level or `before_send` filtering for known-noise patterns (TaoStats 404, cold-cache ratio) before enabling notifications.

### Alert rules

**Existing (MCP `find_alert_rules`):** One enabled issue alert — [“Send a notification for high priority issues”](https://simivision.sentry.io/monitors/alerts/3892979/) (Sentry default template). **Never triggered.** No metric alerts.

**Recommended design (NOT activated — requires Path B filtering first):**

1. **Primary issue alert (production, saga-adjacent):**
   - Filter: `environment:production` AND (`level:error` OR transaction in `/subnetsummer`, `/api/pump-alerts`, `/api/daily-pick`)
   - Trigger: issue seen ≥ 1 time (first occurrence)
   - Action frequency / cooldown: **60 minutes** per issue (storm-safe baseline)

2. **Do NOT alert on (until Path B `before_send` / logger filter):**
   - `logger:fetchers.taostats_client` — TaoStats 404 warnings ([PYTHON-FASTAPI-5](https://simivision.sentry.io/issues/PYTHON-FASTAPI-5)); 51% of current volume
   - Cold-cache ratio warnings ([PYTHON-FASTAPI-4](https://simivision.sentry.io/issues/PYTHON-FASTAPI-4)) — operational noise unless ratio sustained > threshold across multiple cycles

3. **Scrubbing notes (Path B):**
   - Add `before_send` scrubber for Telegram `@handles` in message-intel / pump alert payloads before any alert routes message bodies to Slack/email
   - Confirm no prompt/completion bodies in Sentry extras (currently none observed on sampled events)

4. **Escalation (post-filter):**
   - Loop-stall guard ([PYTHON-FASTAPI-9](https://simivision.sentry.io/issues/PYTHON-FASTAPI-9), [PYTHON-FASTAPI-A](https://simivision.sentry.io/issues/PYTHON-FASTAPI-A)) — consider separate alert with 30-min cooldown once release tagging enables regression detection

### Unavailable/pending (Wave 2 MCP)

1. Sentry org plan/tier/quota via MCP (manual: Settings → Subscription)
2. `SENTRY_RELEASE` on production (no release tag on any prod event)
3. Saga production capture for `/subnetsummer` and `/api/pump-alerts`
4. Path B baseline (not approved)
5. Alert rule activation (blocked until TaoStats / cold-cache filtering designed in Path B)

---

## Blocking gates before Path B

1. P3 quota/tier review with real volume data — **partial:** volume observed (39/24h); plan/tier still unavailable via MCP  
2. P2 build-time `SENTRY_RELEASE` from git SHA in Dockerfile/deploy workflow  
3. Production or natural saga-route failure evidence for `/subnetsummer` and `/api/pump-alerts` — **still pending**  
4. Explicit Path B approval  
5. Alert rule grouping verified — **done via MCP**; activation blocked until noise filters  

---

## Single next action

**Implement P2 build-time `SENTRY_RELEASE`** (Dockerfile ARG → image env) so production events carry deploy SHA — unblocks regression detection and alert rule `#by release` filters. Alternative if Path B approved first: add TaoStats 404 `before_send` drop in `sentry_setup.py` to cap storm risk before activating alerts.

---

## Security

- DSN stored only as Fly secret — never committed to repo.
- If DSN was exposed in chat, rotate in Sentry Project Settings → Client Keys and update Fly secret.
