# Phase 3 Track 3 — Fly log drain proposal (forward-looking)

| Field | Value |
|---|---|
| Status | **PROPOSAL READY** — awaiting Joshua sink choice + deploy approval |
| Pin | `ce3d820013d45577333ac8aada8c0d9e97c54129` |
| PR | [#1324](https://github.com/cryptoreporthub/subnet-dashboard/pull/1324) |
| Inventoried | 2026-10-06T12:37:00Z |
| Joshua grant | Track 3 permission granted 2026-10-06 (plan + investigate; **no deploy without explicit fly approval**) |

**Goal:** Prevent future INC-* investigations from hitting Fly buffer ceiling (~100 lines / ~20 min).

**Not retroactive** — cannot recover 2025-10-05 logs. Forward-looking recurrence prevention only.

---

## Problem statement

| Evidence | Source |
|---|---|
| INC-A/B/C windows NOT_OBSERVABLE | Fly log buffer + logs API 401; Grok rev3 four-method ladder |
| No drain today | Grok rev3 `flyctl apps list` (single app); git grep @ pin clean |
| Buffer ceiling | ~100 lines; earliest line in buffer often hours after incident |
| Sentry gap | Track 1 auth blocked — drain reduces sole reliance on Sentry for forensics |

---

## Inventory (2026-10-06 re-check)

| Check | Result | Receipt |
|---|---|---|
| Log-shipper Fly app | None (Grok rev3: single org, one app) | [`grok-fly-triage-rev3-2026-10-06.md`](grok-fly-triage-rev3-2026-10-06.md) §3 |
| `flyctl apps list` (this session) | **unauthorized** (`01M48K54VRPT0WM4405JGB234A-lax`) — SSH works, org list blocked on cloud token | 2026-10-06T12:37Z |
| Repo references (axiom/papertrail/datadog/NATS/logtail) | **0 hits** @ pin `ce3d8200` in `fly.toml`, `Dockerfile`, `*.yml`, `*.md` | `git grep` @ pin |
| Fly LogShipper sidecar | Not configured | `fly.toml` @ pin — single `[processes] web` only |
| NATS/log shipper in app code | None for Fly logs | `internal/bots/shield.py` documents missing shipper as degraded freshness only |

---

## Recommended approach

**Primary recommendation: Fly Log Shipper → Axiom** (or Better Stack if org already has account)

| Option | Pros | Cons | Complexity |
|---|---|---|---|
| **Fly Log Shipper + Axiom** | Native Fly integration; no app code change; query retention 30d+ | New Fly app + Axiom account; secrets | Medium |
| Better Stack (Logtail) | Simple HTTP ingest; good UI | Third-party cost; separate from Fly metrics | Low–medium |
| Papertrail | Mature, simple | Smaller query UX vs Axiom | Low |
| Sidecar in `subnet-dashboard` | Co-located | Violates single-process v1 topology; volume split-brain risk per `fly.toml` comments | **Not recommended** |

**Pick:** Fly Log Shipper as a **separate Fly app** in the same org (matches Grok “no second machine on subnet-dashboard” constraint).

---

## Implementation plan (requires Joshua deploy approval)

### Phase A — sink setup (human)

1. Create Axiom dataset `subnet-dashboard-prod` (or Better Stack source).
2. Copy ingest token (not committed to git).

### Phase B — Fly Log Shipper app (ops PR / Ditto Code)

1. `fly apps create subnet-dashboard-logshipper` (name TBD) in `sjc`.
2. Deploy [Fly Log Shipper](https://github.com/superfly/fly-log-shipper) template with NATS consumer for `subnet-dashboard` logs.
3. Set secrets (example for Axiom):
   ```bash
   fly secrets set -a subnet-dashboard-logshipper \
     ORG=personal \
     ACCESS_TOKEN=<fly-api-token-read-logs> \
     AXIOM_DATASET=subnet-dashboard-prod \
     AXIOM_TOKEN=<axiom-ingest-token>
   ```
4. **Do not** modify `subnet-dashboard` `fly.toml` VM size or process groups without explicit approval.

### Phase C — verify (read-only)

1. Trigger a known log line (e.g. `GET /health`) and confirm arrival in Axiom within 60s.
2. Document retention policy and query URL in post-install receipt below.
3. Confirm query span > 20 min (buffer ceiling exceeded).

### Cost estimate (order of magnitude)

| Item | Estimate |
|---|---|
| Fly Log Shipper app | shared-cpu-1x ~$5–7/mo |
| Axiom free tier | 500 GB ingest/mo — sufficient for single-app info logs |
| Engineering | ~2–4h first-time setup |

---

## Dry-run commands (read-only, safe)

```bash
# Confirm no shipper references at pin (already run — 0 hits)
git grep -iE 'log-shipper|logtail|axiom|papertrail' ce3d820013d45577333ac8aada8c0d9e97c54129 -- '*.toml' '*.yml' 'Dockerfile' '*.md'

# Confirm prod still on pin (no drain dependency)
curl -sS https://subnet-dashboard.fly.dev/version
```

**Not run (gated):** `fly secrets set`, `fly deploy`, volume changes.

---

## Sequence

Track 3 implementation runs **after** Joshua picks sink + approves Fly secrets/deploy. Tracks 1–2 retroactive ceiling documented (Sentry NOT_OBSERVABLE; Finding D CONFIRMED).

---

## Approval record

| Field | Value |
|---|---|
| Joshua approval (investigate + propose) | **GRANTED** 2026-10-06 |
| Joshua approval (deploy / secrets) | **PENDING** |
| Approved sink | — (recommend Axiom via Fly Log Shipper) |
| Approved implementation path | — |
| Target deploy PR / ticket | — (separate from PR #1324) |

---

## Post-install receipt (future)

- [ ] Shipper app name + region
- [ ] Retention days + query URL
- [ ] Sample log line with UTC timestamp proving span beyond Fly buffer
- [ ] No secrets in git
