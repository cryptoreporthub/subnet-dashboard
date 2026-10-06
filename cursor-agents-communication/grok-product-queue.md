# Grok product pipeline queue (repo source of truth)

> **Boot:** read this file first (pinned SHA). Ditto mirrors optional (`grok-product-queue-active-2026-10-06`).
> **Poll:** Grok routine every 3–5 min when `state=WAITING_GROK`; MC routine when `state=WAITING_MC`.

## STATUS

| Field | Value |
|-------|-------|
| `main` | `245ff24e` |
| `active_slice` | **P4a** |
| `state` | `WAITING_GROK` |
| `updated` | `2026-10-06T19:40Z` |
| `plan` | `/cursor/stores/self/docs/post-audit-p1-p4-plan.md` |

## Serial queue

| # | Slice | Owner | Branch | State |
|---|-------|-------|--------|-------|
| 1 | P1 universe shrink | Grok | `cursor/p1-universe-shrink-fix` | **DONE** — [PR #1326](https://github.com/cryptoreporthub/subnet-dashboard/pull/1326) Ready @ `7c020112` |
| 2 | **P4a** resolver lock | Grok | `cursor/p4a-resolver-lock-timeout` | **ACTIVE** `WAITING_GROK` |
| 3 | P2 F02 Gate C | MC | `cursor/p2-f02-gate-c-receipts` | queued |
| 4 | P3a council/signals | Grok | `cursor/p3a-council-signals` | queued |
| 5 | P3b chat streaming | Grok | `cursor/p3b-simivision-chat-stream` | queued |
| 6 | P3c message-intel | Grok | `cursor/p3c-message-intel-live` | queued |
| 7 | P4b guard calibrate | Grok | `cursor/p4b-stall-guard-calibrate` | conditional |

---

## P4a handoff (ACTIVE)

**Ditto:** `grok-p4a-resolver-lock-handoff-2026-10-06` (`791c674d`)  
**Report section:** append `## P4a report` below when done  
**base:** `main` @ `245ff24e`  
**branch:** `cursor/p4a-resolver-lock-timeout`

**PROBLEM:** Resolver cycles overrun 360s timeout. `revive` returns `tick_in_progress` when `_cycle_lock` held (`resolver_scheduler.py` ~1351–1357). Stall guard cannot recover.

**FILES:** `internal/council/resolver_scheduler.py`

**FIX:** Ensure timeout releases lock; harden revive recycle when stale lock after timeout; tests.

**AC:**
- targeted pytest green
- `tests/test_endpoint_contract.py` 148 passed
- draft PR + append report section here (PR URL + head SHA)
- optional Ditto `save_memory` report mirror
- no deploy; no `RESOLVER_*` bumps

---

## P1 report (DONE)

- **PR:** https://github.com/cryptoreporthub/subnet-dashboard/pull/1326
- **head:** `7c020112`
- **MC verdict:** PASS — Ready for review

## P4a report

_(pending — Grok fills on completion)_
