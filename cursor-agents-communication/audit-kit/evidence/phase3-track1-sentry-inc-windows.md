# Phase 3 Track 1 — Sentry INC window search

| Field | Value |
|---|---|
| Status | **PENDING** |
| Blocker | Sentry MCP `needsAuth` (auth timed out in MC session 2026-10-06) |
| Pin | `ce3d820013d45577333ac8aada8c0d9e97c54129` |
| PR | [#1324](https://github.com/cryptoreporthub/subnet-dashboard/pull/1324) |
| Opened | 2026-10-06 (post–Tier A) |
| Prod hint | `/version` exposes `sentry_release`; app is Sentry-instrumented at pin |

**Goal:** Replace missing Fly log lines for 2025-10-05 incident windows if events were captured in Sentry.

---

## Incident windows

| claim_id | UTC window | Sentry query focus | Verdict | Event IDs | Notes |
|---|---|---|---|---|---|
| L2-INC-A-001 | 2025-10-05 08:29–08:55 | GHA curl 000000, `/api/ops/live`, timeouts, ASGI stall | PENDING | — | |
| L2-INC-B-001 | 2025-10-05 11:41:30–11:47:23 | machine recycle 11:45:48Z, exit 137, health flap | PENDING | — | |
| L2-INC-C-001 | 2025-10-05 11:44–11:54 (center 11:49:15) | static wedge, `/static/*`, thread pool | PENDING | — | |

---

## Query hints (Sentry UI or MCP)

- **Project:** subnet-dashboard (confirm in Sentry org)
- **Time range:** per window above (UTC)
- **Filters:** `transaction:/health`, `transaction:/api/ops/live`, `message:*timeout*`, `message:*stall*`, level:error
- **Release correlate:** match `sentry_release` from live `/version` to pin deploy
- **Do not:** upgrade ledger `disposition` from NOT_OBSERVABLE/BOUNDED_UNKNOWN without event-level receipt

---

## Methods attempted

| Method | Result | Receipt |
|---|---|---|
| Sentry MCP search | BLOCKED | MCP namespace `needsAuth` |
| Fly log buffer | NOT_OBSERVABLE | [`grok-fly-triage-rev3-2026-10-06.md`](grok-fly-triage-rev3-2026-10-06.md) |
| Manual UI export | NOT RUN | Awaiting Joshua Sentry MCP auth or UI export |

---

## Unblock

1. Joshua authenticates Sentry MCP in Cursor, **or**
2. Export/search in Sentry UI for the three windows and attach event IDs + timestamps here.

**Success:** per-window CONFIRMED / REFUTED / NOT_OBSERVABLE with event IDs (honest ceiling if still empty).
