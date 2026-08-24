# Sentry Telemetry Findings

**Directive:** Sentry Telemetry Review v1.1  
**Evidence tiers:** Confirmed from code | Confirmed from tests | Confirmed locally at runtime | Confirmed in production | Historical evidence | Unavailable/pending

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

## Blocking gates before Path B

1. P3 quota/tier review with real volume data  
2. P2 build-time `SENTRY_RELEASE` from git SHA in Dockerfile/deploy workflow  
3. Production or natural saga-route failure evidence  
4. Explicit Path B approval  
5. Alert rule grouping verified before activation  

---

## Single next action

**Authenticate Sentry MCP in Cursor Desktop** (Settings → MCP → sentry → Connect), then re-run Wave 2 read-only probe for issues, grouping, and quota.

Optional: Open Sentry project Issues and filter `environment:production` for verify messages `subnet-dashboard prod-agent-verify-wave2` and `subnet-dashboard sentry-agent-verify-local`.

---

## Security

- DSN stored only as Fly secret — never committed to repo.
- If DSN was exposed in chat, rotate in Sentry Project Settings → Client Keys and update Fly secret.
