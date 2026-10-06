# Phase 3 Track 1 — Sentry INC window search

| Field | Value |
|---|---|
| Status | **COMPLETE** (honest ceiling — auth blocked) |
| Executed | 2026-10-06T12:35:00Z |
| Pin | `ce3d820013d45577333ac8aada8c0d9e97c54129` |
| PR | [#1324](https://github.com/cryptoreporthub/subnet-dashboard/pull/1324) |
| Prod hint | `/version` → `sentry_release`: `ce3d820013d45577333ac8aada8c0d9e97c54129` |
| Gate | Joshua granted Track 1 read-only 2026-10-06 |

**Goal:** Replace missing Fly log lines for 2025-10-05 incident windows if events were captured in Sentry.

---

## Incident windows — verdicts

| claim_id | UTC window | Sentry query focus | Verdict | Event IDs | Notes |
|---|---|---|---|---|---|
| L2-INC-A-001 | 2025-10-05 08:29–08:55 | GHA curl 000000, `/api/ops/live`, timeouts, ASGI stall | **NOT_OBSERVABLE** | — | Sentry MCP auth timed out; no UI export |
| L2-INC-B-001 | 2025-10-05 11:41:30–11:47:23 | machine recycle 11:45:48Z, exit 137, health flap | **NOT_OBSERVABLE** | — | Same auth blocker |
| L2-INC-C-001 | 2025-10-05 11:44–11:54 (center 11:49:15) | static wedge, `/static/*`, thread pool | **NOT_OBSERVABLE** | — | Same auth blocker |

**Ledger:** `mechanism_status` remains **BOUNDED_UNKNOWN** for all three — no NOT_OBSERVABLE→CONFIRMED upgrade without event-level receipt.

---

## Methods attempted

| Method | Result | Receipt |
|---|---|---|
| Sentry MCP `mcp_auth` | **FAILED** | `Error: MCP authentication timed out` (2026-10-06 MC worker session) |
| Sentry MCP `search_events` / `search_issues` | **BLOCKED** | Namespace status `needsAuth` — tools unavailable pre/post auth attempt |
| Fly log buffer | NOT_OBSERVABLE | [`grok-fly-triage-rev3-2026-10-06.md`](grok-fly-triage-rev3-2026-10-06.md) |
| Manual UI export | NOT RUN | Joshua must auth MCP or run UI queries below |

---

## Manual Sentry UI queries (for Joshua)

**Project:** `subnet-dashboard` (confirm in Sentry org)  
**Release filter:** `release:ce3d820013d45577333ac8aada8c0d9e97c54129`  
**Environment:** `production` (if used)

### L2-INC-A-001 — `2025-10-05T08:29:00` → `2025-10-05T08:55:00` UTC

```
is:unresolved OR level:error
release:ce3d820013d45577333ac8aada8c0d9e97c54129
timestamp:>=2025-10-05T08:29:00 timestamp:<=2025-10-05T08:55:00
(transaction:/api/ops/live OR transaction:/health OR message:*timeout* OR message:*stall*)
```

### L2-INC-B-001 — `2025-10-05T11:41:30` → `2025-10-05T11:47:23` UTC

```
level:error OR message:*137* OR message:*SIGKILL* OR message:*health*
release:ce3d820013d45577333ac8aada8c0d9e97c54129
timestamp:>=2025-10-05T11:41:30 timestamp:<=2025-10-05T11:47:23
```

### L2-INC-C-001 — `2025-10-05T11:44:00` → `2025-10-05T11:54:00` UTC

```
transaction:/static/* OR message:*static* OR message:*thread* OR message:*wedge*
release:ce3d820013d45577333ac8aada8c0d9e97c54129
timestamp:>=2025-10-05T11:44:00 timestamp:<=2025-10-05T11:54:00
```

**Discover URL pattern:** `https://<org>.sentry.io/discover/results/?query=<encoded>&statsPeriod=24h&start=2025-10-05T08:29:00&end=2025-10-05T11:54:00`

---

## Unblock (remaining)

1. Joshua authenticates Sentry MCP in Cursor (retry `mcp_auth` on namespace `Sentry`), **or**
2. Run the three UI queries above and paste event IDs + timestamps into this file.

**Success criteria met:** per-window honest NOT_OBSERVABLE with auth receipt; manual query strings provided for Joshua.
