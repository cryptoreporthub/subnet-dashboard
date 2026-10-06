# Phase 3 Track 1 — Sentry INC window search

| Field | Value |
|---|---|
| Status | **CLOSED — Sentry unavailable** (free tier expired; no paid plan) |
| Closed | 2026-10-06T14:00:00Z |
| Pin | `ce3d820013d45577333ac8aada8c0d9e97c54129` |
| PR | [#1324](https://github.com/cryptoreporthub/subnet-dashboard/pull/1324) |
| Prod hint | `/version` → `sentry_release`: `ce3d820013d45577333ac8aada8c0d9e97c54129` |
| Gate | Joshua granted Track 1 read-only 2026-10-06 |

**Goal:** Replace missing Fly log lines for 2025-10-05 incident windows if events were captured in Sentry.

**Closure:** Sentry free tier expired; org has no paid plan. **Do not retry Sentry MCP or UI queries.** Track 1 is closed with honest NOT_OBSERVABLE verdicts for all three Oct-5 app-log windows.

---

## Incident windows — verdicts (final)

| claim_id | UTC window | Sentry query focus | Verdict | Event IDs | Notes |
|---|---|---|---|---|---|
| L2-INC-A-001 | 2025-10-05 08:29–08:55 | GHA curl 000000, `/api/ops/live`, timeouts, ASGI stall | **NOT_OBSERVABLE** | — | Sentry unavailable (unpaid); partial GHA evidence only (see ladder §1) |
| L2-INC-B-001 | 2025-10-05 11:41:30–11:47:23 | machine recycle 11:45:48Z, exit 137, health flap | **NOT_OBSERVABLE** | — | Sentry unavailable; prior GraphQL lifecycle receipt retained |
| L2-INC-C-001 | 2025-10-05 11:44–11:54 (center 11:49:15) | static wedge, `/static/*`, thread pool | **NOT_OBSERVABLE** | — | Sentry unavailable; audit-time static burst only |

**Ledger:** `mechanism_status` remains **BOUNDED_UNKNOWN** for all three — no NOT_OBSERVABLE→CONFIRMED upgrade without event-level receipt.

---

## Alternative evidence ladder (no Sentry)

Retroactive Oct-5 **app logs** cannot be recovered. This ladder documents what remains observable without Sentry.

| # | Method | INC-A | INC-B | INC-C | Receipt |
|---|---|---|---|---|---|
| 1 | **GHA workflow logs** | **PARTIAL** — run `37283988892` (0-byte `/health`, `/api/ops/live`, curl timeouts @ 08:43Z) | No GHA run in 11:41–11:47Z window | N/A (static burst only) | [`l2-inc-phase2-multi-method-2026-10-06T03:36:37Z.txt`](l2-inc-phase2-multi-method-2026-10-06T03:36:37Z.txt); [`L2-INC-A-001.json`](../findings/L2-INC-A-001.json) |
| 2 | **Fly flyctl buffer** | **NOT_OBSERVABLE** | **NOT_OBSERVABLE** | **NOT_OBSERVABLE** | ~100 lines / ~20 min retention; 0 overlap with Oct-5 windows — [`grok-fly-triage-rev3-2026-10-06.md`](grok-fly-triage-rev3-2026-10-06.md) |
| 3 | **Gate C read-only prod state** | Live state only (not historical logs) | Same | Same | Track 2 style — Finding D netuids named @ `796a37ed`; does not recover incident-time logs — [`phase3-finding-d-netuids-2026-10-06.md`](phase3-finding-d-netuids-2026-10-06.md) |
| 4 | **Track 3 log drain** | Forward prevention only | Forward prevention only | Forward prevention only | Cannot retroactively recover Oct-5 — [`phase3-track3-log-drain-proposal.md`](phase3-track3-log-drain-proposal.md) |

**Audit ceiling:** INC-A/B/C Oct-5 **mechanism** windows stay NOT_OBSERVABLE for app logs. Tier A closure stands; Phase 3 Track 1 adds no disposition upgrade.

---

## Methods attempted (Sentry path — abandoned)

| Method | Result | Receipt |
|---|---|---|
| Sentry MCP `mcp_auth` | **FAILED** | `Error: MCP authentication timed out` (2026-10-06 MC worker session) |
| Sentry MCP `search_events` / `search_issues` | **BLOCKED** | Namespace status `needsAuth` — tools unavailable pre/post auth attempt |
| Sentry org / paid plan | **UNAVAILABLE** | Free tier expired; no paid plan — **Track 1 CLOSED** 2026-10-06 |
| Fly log buffer | NOT_OBSERVABLE | [`grok-fly-triage-rev3-2026-10-06.md`](grok-fly-triage-rev3-2026-10-06.md) |

---

## Superseded: Manual Sentry UI queries

~~Joshua authenticates Sentry MCP or runs Discover queries.~~ **Superseded** — Sentry unpaid; queries would not yield retained Oct-5 events on expired free tier. Retained for historical record only in git history prior to this close.

---

## Success criteria met

- Per-window honest NOT_OBSERVABLE with Sentry-unavailable receipt
- Alternative evidence ladder documented (GHA partial → Fly buffer ceiling → Gate C live-only → Track 3 forward-only)
- No false NOT_OBSERVABLE→CONFIRMED upgrade on INC mechanism claims
