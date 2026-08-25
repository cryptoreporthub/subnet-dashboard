# Sentry Telemetry Findings

**Directive:** Sentry Telemetry Review v1.1
**Evidence tiers:** Confirmed from code | Confirmed from tests | Confirmed locally at runtime | Confirmed in production | Confirmed via Sentry MCP | Confirmed in production via MCP | Historical evidence | Unavailable/pending

**Tier usage:**
- **Confirmed via Sentry MCP** — account/project queries, issue inventory via MCP API, alert-rule inspection, intentional verify-issue resolution.
- **Confirmed in production via MCP** — production telemetry facts: event environment, counts, route context, production issue/event data.

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

**Saga (Wave 1):** Local mechanism verified; production natural capture pending; local automated saga gate added 2026-08-25 (`tests/test_sentry_saga_gate.py`).

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

**Scope:** Read-only telemetry inspection plus resolution of two intentional verification issues. No application code, Fly secret, or deployment changes.

### MCP authentication

| Check | Tier | Result |
|-------|------|--------|
| Sentry MCP `whoami` | Confirmed via Sentry MCP | Authenticated account confirmed; personal account identifiers omitted |
| `find_organizations` | Confirmed via Sentry MCP | Org **simivision** → [simivision.sentry.io](https://simivision.sentry.io), region `https://us.sentry.io` |
| `find_projects` | Confirmed via Sentry MCP | Project **python-fastapi** (sole project) |

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

**Grouping observations (Confirmed in production via MCP):**

- Issues group cleanly by logger message / route (TaoStats 404, cold-cache ratio, daily-pick timeout, resolver timeout, loop-stall guard).
- Production events carry `environment:production`, `server_name` (Fly machine), runtime tags — **no `release` tag** on any production event.
- Local verify ([PYTHON-FASTAPI-1](https://simivision.sentry.io/issues/PYTHON-FASTAPI-1)) had `environment:development` and `release: 95f7e0c4…` (git SHA from local env, not Fly image).

### Verify issues (resolved as test noise)

| Issue | Tier | Action |
|-------|------|--------|
| PYTHON-FASTAPI-1 (`sentry-agent-verify-local`) | Confirmed via Sentry MCP | **Resolved** — intentional local transport test |
| PYTHON-FASTAPI-8 (`prod-agent-verify-wave2`) | Confirmed via Sentry MCP | **Resolved** — intentional prod transport test |

### Saga gate (P1 amended)

| Route / path | Prod/natural Sentry events? | Tier |
|--------------|----------------------------|------|
| `/subnetsummer` | **No** (7d) | Confirmed in production via MCP |
| `/api/pump-alerts` | **Yes** — timeout warnings (`pump-alerts timed out after 12s`, culprit `/api/pump-alerts`) | Confirmed in production via MCP |
| `/api/daily-pick` | Yes — [PYTHON-FASTAPI-6](https://simivision.sentry.io/issues/PYTHON-FASTAPI-6) (timeout warnings, 4 events) | Confirmed in production via MCP |
| listener / message-intel | **No** | Confirmed in production via MCP |

**Status (2026-08-25):** Transport and initialization verified in production. **No natural prod failure events** yet for `/subnetsummer` or `/api/pump-alerts` (routes healthy when checked). **Local saga gate cleared** via `tests/test_sentry_saga_gate.py` — TestClient synthetic failures confirm Starlette request URLs attach for both routes (`Confirmed locally at runtime`). Synthetic prod verify (`fly machine exec`) skipped — flyctl MCP unavailable on agent VM.

Wave 1 local mock capture for `/subnetsummer` and `/api/pump-alerts` remains **Confirmed locally at runtime** (automated tests + before_send matrix in `tests/test_sentry_setup.py`).

### P3 quota / tier gate

| Item | Tier | Notes |
|------|------|-------|
| Observed production volume | Confirmed in production via MCP | 39 events / 24h, 41 / 7d (observation window shortly after transport enable) |
| TaoStats initial rate signal | Confirmed in production via MCP | During the approximately one-hour post-enable observation window, 20 TaoStats events were observed ([PYTHON-FASTAPI-5](https://simivision.sentry.io/issues/PYTHON-FASTAPI-5), 51% of 24h volume). This is an **initial rate signal**, not a stable 24-hour baseline. |
| Code risk estimate (~423 `logger.warning` sites) | Confirmed from code | Ceiling estimate, not measured — prod already shows warning-level ingest at scale |
| Sentry plan/tier/quota limits | **Unavailable/pending** | No MCP tool exposes org billing/quota; manual dashboard check required |

**Storm assessment:** During the short post-enable window, TaoStats warnings dominated ingest. Alerting on all `level:warning` production events without filtering would likely cause notification fatigue. Path B should add logger-level or `before_send` filtering for known-noise patterns (TaoStats 404, cold-cache ratio) before enabling notifications.

### Alert rules

**Existing (MCP `find_alert_rules`, Confirmed via Sentry MCP):** One enabled issue alert — [“Send a notification for high priority issues”](https://simivision.sentry.io/monitors/alerts/3892979/) (Sentry default template). **Never triggered.** No metric alerts.

**Recommended design (NOT activated — requires Path B filtering first):**

1. **Primary issue alert (production, saga-adjacent):**
   - Filter: `environment:production` AND (`level:error` OR transaction in `/subnetsummer`, `/api/pump-alerts`, `/api/daily-pick`)
   - Trigger: issue seen ≥ 1 time (first occurrence)
   - Action frequency / cooldown: **60 minutes** per issue (storm-safe baseline)

2. **Do NOT alert on (until Path B `before_send` / logger filter):**
   - `logger:fetchers.taostats_client` — TaoStats 404 warnings ([PYTHON-FASTAPI-5](https://simivision.sentry.io/issues/PYTHON-FASTAPI-5)); 51% of observed volume in the short window
   - Cold-cache ratio warnings ([PYTHON-FASTAPI-4](https://simivision.sentry.io/issues/PYTHON-FASTAPI-4)) — operational noise unless ratio sustained > threshold across multiple cycles

3. **Scrubbing notes (Path B):**
   - Add `before_send` scrubber for Telegram `@handles` in message-intel / pump alert payloads before any alert routes message bodies to Slack/email
   - Confirm no prompt/completion bodies in Sentry extras (currently none observed on sampled events)

4. **Escalation (post-filter):**
   - Loop-stall guard ([PYTHON-FASTAPI-9](https://simivision.sentry.io/issues/PYTHON-FASTAPI-9), [PYTHON-FASTAPI-A](https://simivision.sentry.io/issues/PYTHON-FASTAPI-A)) — consider separate alert with 30-min cooldown once release tagging enables regression detection

### Unavailable/pending (Wave 2 MCP) — historical snapshot

1. Sentry org plan/tier/quota via MCP (manual: Settings → Subscription) — **still pending**
2. `SENTRY_RELEASE` on production — **was** `release=null` pre-Stage C; **merged #1042** (2026-08-25); deploy + post-deploy verify pending
3. Saga production capture — `/api/pump-alerts` **confirmed in prod** (timeout warnings); `/subnetsummer` **local gate cleared** (`tests/test_sentry_saga_gate.py`); prod natural `/subnetsummer` still pending
4. Path B scrub/filter — **authorized and merged** (#1038, 2026-08-24)
5. Alert rule activation — **deferred** (Stage D; see below)

---

## Blocking gates — superseded timeline (2026-08-25)

Historical Wave 2 gates above reflected pre-approval state. Current status:

| Gate | Status |
|------|--------|
| Path B scrub/filter (#1038) | **MERGED**; live on prod; TaoStats pool-latest 404 **0 events / 1h** post-deploy |
| Path B explicit approval | **Granted** 2026-08-24 |
| Stage C release build (#1042) | **MERGED** 2026-08-25 — deploy + `SENTRY_RELEASE` verify pending |
| Saga gate tests (#1044) | **MERGED** 2026-08-25 |
| P5 browser plan (#1043) | **MERGED** 2026-08-25 (docs only; not implementation approval) |
| P3 quota/tier | Manual dashboard — **still pending** |
| Saga `/subnetsummer` prod natural | **Pending** (route healthy; local tests pass) |
| Saga `/api/pump-alerts` prod | **Confirmed** (timeout warnings in Sentry) |
| Stage D alerts | **Documented**; activate ≥24h post-scrub in Sentry UI |
| D5 #1041 parallel work | **No file collision** with Sentry PRs (`server.py` only on #1041) |

---

## Execution plan — agent-owned merges (2026-08-25)

Owner authorized agent to merge Sentry PRs. **Parallel D5 #1041** is orthogonal (`server.py` / universe feed only).

| Step | Action | Owner | Status |
|------|--------|-------|--------|
| 1 | Merge **#1042** Stage C (`SENTRY_RELEASE`) | Agent | **DONE** (`19fbb126`) |
| 2 | Fly deploy (push to `main` or `workflow_dispatch`) | CI auto on push | **Pending** — follows merge |
| 3 | Post-deploy: machine `SENTRY_RELEASE` == deploy SHA; new events carry `release` | Agent/human verify | Pending after deploy |
| 4 | Merge **#1044** saga gate tests (rebase findings doc) | Agent | In progress |
| 5 | Merge **#1043** P5 browser plan (docs only) | Agent | After #1044 |
| 6 | Stage D alert rules in Sentry UI | Human | ≥24h post-scrub + quota check |
| 7 | P5 Browser SDK **implementation** | Separate approval | **Not authorized** |

**Do not** bundle Browser SDK runtime code, Session Replay, or hydration/`cockpit_hydrate.js` changes into Sentry merges.

**Conflict surface:** Resolved — all Sentry PRs merged. **D5 #1041** remains independent (`server.py` only).

---

## Historical recommendations (Wave 2 — pre-approval)

These items were **not authorized** when Wave 2 findings were first written. They are **superseded** by merges and owner authorization on 2026-08-24/25:

- P2 build-time `SENTRY_RELEASE` → implemented in **Stage C PR #1042**
- Path B `before_send` filtering → **merged #1038**

Do not treat the historical “not authorized by this PR” wording as current policy.

---

## Stage B status (2026-08-25)

| Item | Tier | Notes |
|------|------|-------|
| Scrub/filter on `main` | CI | Merged #1038 (`c0494297`) |
| Prod scrub active | production | Fly `v2008`; `before_send` drops TaoStats pool-latest 404 via SSH verify |
| TaoStats 404 ingest post-scrub | production | Monitor via Sentry MCP; baseline clock from deploy ~2026-08-25T06:04 UTC |

---

## Stage C — release build (**merged #1042**, 2026-08-25)

Build-time `GIT_SHA` → `SENTRY_RELEASE` in Dockerfile + `fly.yml` `--build-arg`. Merged to `main` (`19fbb126`).

**Next:** Fly deploy (CI on push to `main`); post-deploy verify machine `SENTRY_RELEASE` matches deploy SHA; confirm new prod events carry `release` tag.

---

## Stage D — alert activation (manual UI; ≥24h after scrub baseline)

Sentry MCP has no alert-create tool. Configure in Sentry UI after 24h stable post-scrub volume + quota check (Settings → Subscription).

### Before activating

1. Disable or narrow default rule “Send a notification for high priority issues” (0 min cooldown — storms on warnings).
2. Confirm TaoStats `PYTHON-FASTAPI-5` ingest `count() = 0` over 24h window.
3. Confirm quota headroom manually.

### Create: `prod-errors-saga-adjacent`

- Filter: `environment:production` AND `level:error`
- Optional: `transaction:/subnetsummer` OR `/api/pump-alerts` OR `/api/daily-pick`
- Cooldown: **60 minutes** per issue
- **Do not** alert on: `logger:fetchers.taostats_client`, broad `level:warning`, cold-cache ratio, `/api/learning/health` timeouts during deploy

### Optional after Stage C release tags stable

- `prod-loop-stall-guard`: loop-stall messages, 30 min cooldown
- `prod-regression-new-issue`: `level:error` + `is:new` + `release:latest`, 60 min cooldown

### Rollback (alerts only)

Disable new rules; re-enable only after volume re-baselined. No Saga/runtime state changes.

---

## Security

- DSN stored only as Fly secret — never committed to repo.
- If DSN was exposed in chat, rotate in Sentry Project Settings → Client Keys and update Fly secret.

---

## P5 — Browser SDK (plan only; implementation gated)

**Status (2026-08-25):** Phase 0 discovery complete in Wave 1 (`Browser SDK not installed; static JS + CSP documented`). Full implementation blueprint in **[`docs/sentry-browser-sdk-plan.md`](sentry-browser-sdk-plan.md)** — documentation-only PR; no runtime changes.

| Topic | Plan location |
|-------|---------------|
| Prerequisites (Stage C #1042, quota, explicit approval) | `sentry-browser-sdk-plan.md` § Prerequisites |
| Loader placement (`base.html` vs `scripts.html`) | § Loader placement options — recommend `base.html` + shared partial |
| Public DSN / separate client key | § Public DSN strategy |
| CSP (`connect-src`, vendored vs CDN SDK) | § CSP changes |
| Source maps (none initially) | § Source maps strategy |
| Client `beforeSend` scrubbing | § Client-side scrubbing |
| Server+browser deduplication | § Duplicate event deduplication |
| Session Replay | § Separate gated track (P5b — not initial) |
| Conflict surface (`cockpit_hydrate.js`, templates) | § Conflict surface |
| PR branch `cursor/sentry-browser-sdk-*` | § PR strategy — no overlap with #1042 |
| Testing / rollback | § Testing plan, § Rollback plan |

**Do not implement** until Stage C release tags are live on prod, quota gate is checked, and owner grants separate P5 approval.
