# Phase 3 Track 3 — Fly log drain proposal (implementation-ready)

| Field | Value |
|---|---|
| Status | **IMPLEMENTATION_READY** — awaiting Joshua deploy/secrets approval |
| Pin | `ce3d820013d45577333ac8aada8c0d9e97c54129` |
| PR | [#1324](https://github.com/cryptoreporthub/subnet-dashboard/pull/1324) |
| Inventoried | 2026-10-06T14:00:00Z (continuation pass) |
| Joshua grant | Track 3 plan + investigate granted 2026-10-06; **deploy/secrets still PENDING** |

**Goal:** Prevent future INC-* investigations from hitting Fly buffer ceiling (~100 lines / ~20 min).

**Not retroactive** — cannot recover 2025-10-05 logs. Forward-looking recurrence prevention only.

---

## Problem statement

| Evidence | Source |
|---|---|
| INC-A/B/C windows NOT_OBSERVABLE | Fly log buffer + logs API 401; Grok rev3 four-method ladder |
| No drain today | Grok rev3 `flyctl apps list` (single app); git grep @ pin 0 real hits |
| Buffer ceiling | ~100 lines; earliest line in buffer often hours after incident |
| Sentry gap | Track 1 **CLOSED** — free tier expired, unpaid; drain is primary forward forensics path |

---

## Inventory (2026-10-06 continuation pass)

| Check | Result | Receipt |
|---|---|---|
| Log-shipper Fly app | None (Grok rev3: single org, one app) | [`grok-fly-triage-rev3-2026-10-06.md`](grok-fly-triage-rev3-2026-10-06.md) §3 |
| `flyctl apps list` (this session) | **SKIPPED** — `flyctl` not installed on cloud agent VM; `FLY_ACCESS_TOKEN` present in env | 2026-10-06T14:00Z |
| Prod `/version` @ pin | **200** — `ce3d820013d45577333ac8aada8c0d9e97c54129` | `curl -sS https://subnet-dashboard.fly.dev/version` |
| Repo drain refs @ pin | **0 hits** (tight grep: `axiom\|betterstack\|papertrail\|logtail\|log-shipper`) | `git grep -iE 'axiom\|betterstack\|papertrail\|logtail\|log-shipper' ce3d8200` |
| `fly.toml` processes | Single `[processes] web` only — no sidecar | `fly.toml` @ pin |
| App logging hooks | `internal/sentry_setup.py` (`SENTRY_DSN` optional); no Fly log shipper | `server.py`, `internal/worker.py` call `init_sentry()` |
| `internal/bots/shield.py` | Documents honest-empty when logs missing — does not invent shipper | `:707` |
| Better Stack / Axiom env vars in repo | **None** @ pin | `fly.toml` `[env]` block |

---

## Recommended approach

**Primary: Fly Log Shipper → Axiom** (separate Fly app; no `subnet-dashboard` fly.toml change)

| Option | Pros | Cons | Complexity |
|---|---|---|---|
| **Fly Log Shipper + Axiom** | Native Fly NATS integration; no app code change; 30d+ retention | New Fly app + Axiom account; secrets | Medium |
| Better Stack (Logtail) | Simple HTTP ingest; good UI | Third-party cost | Low–medium |
| Papertrail | Mature, simple | Smaller query UX vs Axiom | Low |
| Sidecar in `subnet-dashboard` | Co-located | Violates single-process v1 topology; volume split-brain risk per `fly.toml` comments | **Not recommended** |

**Pick:** Fly Log Shipper as **`subnet-dashboard-logshipper`** in same org, region `sjc` (matches prod).

---

## Implementation steps (Joshua / Ditto Code — docs only)

### Phase A — Axiom sink setup (human, ~10 min)

1. Create [Axiom](https://axiom.co) account (free tier: 500 GB ingest/mo).
2. Create dataset: **`subnet-dashboard-prod`**
3. Create ingest token (Settings → API tokens → ingest). Copy token — **do not commit**.

### Phase B — Fly Log Shipper app (ops)

**B1. Create app (no public IPs):**

```bash
fly apps create subnet-dashboard-logshipper --org personal
fly launch --image flyio/log-shipper:latest --no-public-ips \
  -a subnet-dashboard-logshipper -r sjc --yes
```

**B2. Set NATS source + Axiom sink secrets** (run locally with flyctl auth; **not executed by agents**):

```bash
# Read-only Fly token for org log stream (mint fresh — do not reuse deploy token)
READONLY_TOKEN="$(fly tokens create readonly personal)"

fly secrets set -a subnet-dashboard-logshipper \
  ORG=personal \
  ACCESS_TOKEN="${READONLY_TOKEN}" \
  SUBJECT='logs.subnet-dashboard.>' \
  AXIOM_DATASET=subnet-dashboard-prod \
  AXIOM_TOKEN='<axiom-ingest-token-from-phase-A>'
```

| Secret | Required | Purpose |
|---|---|---|
| `ORG` | yes | Fly org slug (`personal`) |
| `ACCESS_TOKEN` | yes | Read-only PAT for NATS log subscription |
| `SUBJECT` | recommended | Scope to `subnet-dashboard` only (`logs.subnet-dashboard.>`) |
| `AXIOM_DATASET` | yes | Target dataset name |
| `AXIOM_TOKEN` | yes | Axiom ingest API token |
| `QUEUE` | optional | HA queue name if running multiple shipper VMs |

**B3. Verify `fly.toml` internal port** (shipper health checks):

After `fly launch`, confirm Vector internal port **8686** in generated `fly.toml`:

```toml
[[services]]
  http_checks = []
  internal_port = 8686
```

**B4. Deploy shipper** (explicit human approval required):

```bash
fly deploy -a subnet-dashboard-logshipper
```

**Do not modify** `subnet-dashboard` `fly.toml` VM size, `[processes]`, or `[mounts]` without separate approval.

### Phase C — Verification (read-only)

```bash
# 1. Generate a known log line
curl -sS -o /dev/null -w "health=%{http_code}\n" https://subnet-dashboard.fly.dev/health

# 2. Confirm shipper machine healthy
fly status -a subnet-dashboard-logshipper

# 3. Query Axiom (within 60s of step 1)
# Axiom UI: dataset subnet-dashboard-prod → filter:
#   ['fly.app.name'] == "subnet-dashboard" and message contains "health"
# Or CLI (if axiom CLI installed):
#   axiom query "['fly.app.name'] == \"subnet-dashboard\"" \
#     --dataset subnet-dashboard-prod --start-time -5m
```

**Pass criteria:**

- [ ] Log line appears in Axiom within 60s
- [ ] Query span demonstrably > 20 min (exceeds Fly buffer ceiling)
- [ ] Retention policy documented in post-install receipt
- [ ] No secrets in git

---

## Preflight checklist (Joshua)

| # | Item | Status |
|---|---|---|
| 1 | Axiom account + dataset `subnet-dashboard-prod` created | ☐ |
| 2 | Axiom ingest token copied to password manager | ☐ |
| 3 | Fresh `fly tokens create readonly personal` minted | ☐ |
| 4 | `subnet-dashboard-logshipper` app created in `sjc` | ☐ |
| 5 | Secrets set per Phase B2 table | ☐ |
| 6 | Shipper deployed; `fly status` healthy | ☐ |
| 7 | Verification Phase C pass | ☐ |
| 8 | Post-install receipt filed (below) | ☐ |

---

## Cost estimate

| Item | Estimate |
|---|---|
| Fly Log Shipper app | shared-cpu-1x ~$5–7/mo |
| Axiom free tier | 500 GB ingest/mo — sufficient for single-app info logs |
| Engineering | ~2–4h first-time setup |

---

## Dry-run commands (read-only, safe — already run)

```bash
# 0 real drain hits @ pin (tight pattern)
git grep -iE 'axiom|betterstack|papertrail|logtail|log-shipper' \
  ce3d820013d45577333ac8aada8c0d9e97c54129

# Prod still on pin (no drain dependency)
curl -sS https://subnet-dashboard.fly.dev/version
# → {"version":"ce3d820013d45577333ac8aada8c0d9e97c54129",...}
```

**Not run (gated):** `fly secrets set`, `fly deploy`, volume changes, `subnet-dashboard` fly.toml edits.

---

## Sequence

Track 3 implementation runs **after** Joshua completes preflight + approves deploy. Tracks 1–2 retroactive ceiling documented (Sentry CLOSED unpaid; Finding D CONFIRMED netuids 130/132).

---

## Approval record

| Field | Value |
|---|---|
| Joshua approval (investigate + propose) | **GRANTED** 2026-10-06 |
| Joshua approval (deploy / secrets) | **PENDING** |
| Approved sink | — (recommend **Axiom** via Fly Log Shipper) |
| Approved implementation path | — (separate ops PR / Ditto Code ticket) |
| Target deploy PR / ticket | — (not PR #1324) |

---

## Post-install receipt (future)

- [ ] Shipper app name + region
- [ ] Axiom dataset URL + retention days
- [ ] Sample log line with UTC timestamp proving span beyond Fly buffer
- [ ] No secrets in git
