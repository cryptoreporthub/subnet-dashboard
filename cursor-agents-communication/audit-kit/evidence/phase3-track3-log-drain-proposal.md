# Phase 3 Track 3 — Fly log drain proposal (forward-looking)

| Field | Value |
|---|---|
| Status | **AWAITING_JOSHUA_APPROVAL** |
| Pin | `ce3d820013d45577333ac8aada8c0d9e97c54129` |
| PR | [#1324](https://github.com/cryptoreporthub/subnet-dashboard/pull/1324) |
| Opened | 2026-10-06 (post–Tier A) |

**Goal:** Prevent future INC-* investigations from hitting Fly buffer ceiling (~100 lines / ~20 min).

**Not retroactive** — cannot recover 2025-10-05 logs. Forward-looking recurrence prevention only.

---

## Problem statement

| Evidence | Source |
|---|---|
| INC-A/B/C windows NOT_OBSERVABLE | Fly log buffer + logs API 401; Grok rev3 four-method ladder |
| No drain today | `flyctl apps list` — no log-shipper app; git grep @ pin clean |
| Buffer ceiling | ~100 lines; earliest line in buffer often hours after incident |

---

## Inventory (pin-verified, read-only)

| Check | Result | Receipt |
|---|---|---|
| Log-shipper Fly app | None found | [`grok-fly-triage-rev3-2026-10-06.md`](grok-fly-triage-rev3-2026-10-06.md) §3 |
| Repo references (axiom/papertrail/datadog/NATS/logtail) | 0 hits @ pin | Grok rev3 git grep |
| Fly LogShipper sidecar | Not configured | fly.toml @ pin |

---

## Proposed steps (plan → approve → implement)

1. **Choose sink** — Axiom / Better Stack / Papertrail / Fly LogShipper (org preference)
2. **Design** — shipper app vs `[processes]` sidecar vs external agent
3. **Approval gate (Joshua)** — Fly secrets, optional sidecar, external shipper app (fly-mcp standing gate)
4. **Implement** — separate PR / ops ticket (not #1324 docs merge)
5. **Verify** — post-install receipt: sample query spans >20 min, retention policy documented

---

## Sequence

Track 3 runs **after** Track 1–2 close the retroactive question (or document honest ceiling). Drain is recurrence prevention, not audit debt for Tier A.

---

## Approval record

| Field | Value |
|---|---|
| Joshua approval | PENDING |
| Approved sink | — |
| Approved implementation path | — |
| Target deploy PR / ticket | — |

---

## Post-install receipt (future)

- [ ] Shipper app name + region
- [ ] Retention days + query URL
- [ ] Sample log line with UTC timestamp proving span beyond Fly buffer
- [ ] No secrets in git
