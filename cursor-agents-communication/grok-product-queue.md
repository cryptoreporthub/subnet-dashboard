# Grok product pipeline queue (repo source of truth)

> **Boot:** read this file first (pinned SHA). Ditto mirrors optional (`grok-product-queue-active-2026-10-06`).
> **Poll:** Grok routine every 3–5 min when `state=WAITING_GROK`; MC routine when `state=WAITING_MC`.

## STATUS

| Field | Value |
|-------|-------|
| `main` | `b5253e65` |
| `active_slice` | **P3c** |
| `state` | `WAITING_GROK` |
| `updated` | `2026-10-06T22:25Z` |
| `plan` | `/cursor/stores/self/docs/post-audit-p1-p4-plan.md` |

## Serial queue

| # | Slice | Owner | Branch | State |
|---|-------|-------|--------|-------|
| 1 | P1 universe shrink | Grok | `cursor/p1-universe-shrink-fix` | **DONE** — [PR #1326](https://github.com/cryptoreporthub/subnet-dashboard/pull/1326) Ready @ `7c020112` |
| 2 | P4a resolver lock | Grok | `cursor/p4a-resolver-lock-timeout` | **DONE** — [PR #1327](https://github.com/cryptoreporthub/subnet-dashboard/pull/1327) Ready @ `f4ae56b5` |
| 3 | P2 F02 Gate C | MC | `cursor/p2-f02-gate-c-receipts-60a6` | **DONE** — [PR #1328](https://github.com/cryptoreporthub/subnet-dashboard/pull/1328) Ready @ `a862121d` |
| 4 | P3a council/signals | Grok | `cursor/p3a-council-signals` | **DONE** — [PR #1330](https://github.com/cryptoreporthub/subnet-dashboard/pull/1330) Ready @ `7adfafd8` |
| 5 | P3b chat streaming | Grok | `cursor/p3b-simivision-chat-stream` | **DONE** — [PR #1331](https://github.com/cryptoreporthub/subnet-dashboard/pull/1331) Ready @ `fff5979e` |
| 6 | **P3c** message-intel | Grok | `cursor/p3c-message-intel-live` | **ACTIVE** `WAITING_GROK` |
| 7 | P4b guard calibrate | Grok | `cursor/p4b-stall-guard-calibrate` | conditional |

---

## P3c handoff (ACTIVE)

**Owner:** Grok  
**handoff vendorId:** `grok-p3c-message-intel-handoff-2026-10-06`  
**report vendorId:** `grok-p3c-message-intel-report-2026-10-06`  
**base:** `main` @ `b5253e65` (rebase on P3b `#1331` if merged first)  
**branch:** `cursor/p3c-message-intel-live`  
**audit anchor:** [PR #1324](https://github.com/cryptoreporthub/subnet-dashboard/pull/1324) pin `ce3d820013d45577333ac8aada8c0d9e97c54129`

**PROBLEM:** Message-intel (`GET /api/message-intel`, `/api/message-intel/status`) is the most-polled surface on the homepage hydrate path. G0/rev3 and P3a MC review flagged `test_prod_stability` message-intel health-block flakes — SQLite write-lock contention during listener ingest can still wedge the event loop if any hot path escapes `run_in_threadpool`. Listener/outcome status must stay honest-empty without creds and non-empty when creds present; no fake live markers.

**TASK — live message-intel reliability (§17.F6):**
1. **Read-path occupancy** — `GET /api/message-intel` (+ list/authors/topics variants) must not block `/health` under mocked slow SQLite or ingest burst; verify all list/stats paths use threadpool or bounded cache (`internal/message_intel/routes.py`, `engine.py`, `store.py`).
2. **Listener status** — `listener_status()` honest for missing creds, disabled, invalid session, idle-with-session (`tests/test_message_intel_f6.py`); no secrets in API payloads.
3. **Outcome loop** — `outcome_loop_status()` reports `running`/`live` honestly within boot budget; no false stall alerts in first 5 min post-boot (`tests/test_message_intel_outcomes.py`).
4. **Status contract** — `/api/message-intel/status` returns `bot_contract` degraded markers when store/listener unhealthy; homepage `#section-message-intel` SSR visible without opening `<details>`.
5. **Homepage hydrate** — message-intel panel fetch must fail-open (partial/degraded label) like P3b chat warm path; no permanent UI wedge on slow status probe.

**FILES (likely):** `internal/message_intel/{routes,engine,store,listener_service,outcome_loop}.py`, `static/js/*message*`, `tests/test_message_intel_f6.py`, `tests/test_message_intel_harden.py`, `tests/test_prod_stability.py`

**AC:** targeted pytest green; `test_endpoint_contract.py` → **148 passed**; draft PR + Ditto report (`grok-p3c-message-intel-report-2026-10-06`); no deploy; no `fly.toml` / `RESOLVER_*` env bumps; do not start P4b.

**Reference:** P3a/P3b occupancy fixes; `gameplan-beyond-16.md` §F6; `post-audit-sprint-plan.md` §B3 outcomes.

---

## P3b handoff (DONE)

**Owner:** Grok  
**handoff vendorId:** `grok-p3b-chat-stream-handoff-2026-10-06`  
**report vendorId:** `grok-p3b-chat-stream-report-2026-10-06`  
**base:** `main` @ `b5253e65`  
**branch:** `cursor/p3b-simivision-chat-stream`  
**audit anchor:** [PR #1324](https://github.com/cryptoreporthub/subnet-dashboard/pull/1324) pin `ce3d820013d45577333ac8aada8c0d9e97c54129`

**PROBLEM:** SimiVision chat (`POST /api/simivision/chat`) is in the contract (slice 13) and ships JSON + SSE streaming via `internal/simivision/routes.py`, but G0/rev3 showed request-path occupancy during hydrate bursts — chat context build and LLM calls must not block `/health`, homepage warm, or daily-pick reads. Streaming must stay XSS-safe, gzip-exempt, and honest-degraded when providers or executors are saturated.

**TASK — chat streaming reliability:**
1. **JSON + SSE paths** — `?stream=1` and body `stream:true` return `text/event-stream` with `event: meta|chunk|done`; default JSON path unchanged (`tests/test_simivision_chat_stream.py`).
2. **Occupancy guards** — `build_chat_context` must not call live subnet feeds on the hot path; cache TTL honored; chat POST (JSON or stream) must not block `/health` under mocked slow LLM (`tests/test_chat_stability.py`, `test_prod_stability` pattern).
3. **Transport** — GZip middleware skips `/api/simivision/chat` when streaming (`internal/transport.py`; `tests/test_transport.py`).
4. **XSS** — `sanitize_reply` escapes HTML in all outbound reply paths.
5. **Provider routing** — preserve Chutes → Thirty Spokes fallback without blocking on dead Chutes `/models` probe (`test_chat_stability` router tests).

**FILES (likely):** `internal/simivision/routes.py`, `internal/simivision/chat_service.py`, `internal/transport.py`, `static/js/chat_stream.js`, `tests/test_simivision_chat_stream.py`, `tests/test_chat_stability.py`

**AC:** targeted pytest green; `test_endpoint_contract.py` → **148 passed**; draft PR + Ditto report (`grok-p3b-chat-stream-report-2026-10-06`); no deploy; no `fly.toml` / env bumps.

**Reference:** P3a occupancy fixes (`#1330`); `g0-1058-composer-p1-handoff.md` §occupancy (do not add scoring/feeds on read paths).

## P3b report (DONE)

- **PR:** https://github.com/cryptoreporthub/subnet-dashboard/pull/1331
- **head:** `fff5979e`
- **tests:** `test_simivision_chat_stream.py` + `test_chat_stability.py` → **24 passed**; `test_endpoint_contract.py` → **148 passed** (env: `PYTHONPATH=.`).
- **code review:** investigation pool `shutdown(wait=False, cancel_futures=True)` bounds TaoStats strand past budget; `asyncio.wait_for` on chat sync path (`SIMIVISION_CHAT_TIMEOUT_SECONDS`); SSE always terminates with `event:done` (empty reply + timeout partial); `sanitize_reply` on all outbound paths; `chat_stream.js` textContent-only + fail-open warm probe (8s) + 50s send deadline + JSON fallback on stream error; no `fly.toml` / `RESOLVER_*` changes in diff.
- **MC verdict:** **PASS** — Ready for review (MC undrafted)

---

## P3a handoff (DONE)

**Owner:** Grok  
**handoff vendorId:** `grok-p3a-council-signals-handoff-2026-10-06`  
**report vendorId:** `grok-p3a-council-signals-report-2026-10-06`  
**base:** `main` @ `0293bd2f`  
**branch:** `cursor/p3a-council-signals`  
**audit anchor:** [PR #1324](https://github.com/cryptoreporthub/subnet-dashboard/pull/1324) pin `ce3d820013d45577333ac8aada8c0d9e97c54129`

**PROBLEM:** G0 prod repro (`artifacts/g0-baseline/`, `g0-1058-composer-p1-handoff.md`) showed `/api/daily-pick` aborting under homepage hydrate burst and `/health` starvation from request-path occupancy. Rev3 triage checklist #7 (signal cross-check @ incident timestamp) was **PARTIAL** — council busy/empty, endpoints timed out → NOT_OBSERVABLE. Council signal workers (`internal/council/signals/{poller,pathfinder}.py`) are stubs; reliability must come from the existing signal pipeline + read-path guards.

**TASK — council/signals/daily-pick reliability:**
1. **Daily-pick hydrate GET** — cached-today hit returns within tight budget without `get_or_create_today_pick` / full scoring (`server.py` `api_daily_pick`, coalesced flight). Timeout HOLD must carry `_meta.stale:true` and must not masquerade as scheduler HOLD.
2. **Homepage/council read paths** — verify no remaining hydrate callers invoke `get_or_create_today_pick` (`internal/learning/dashboard_context.py`, `_home_hero_context`, `_pick_sections`). Read stored JSON only.
3. **Signals under load** — `/api/signals` + `/api/signals/summary` return honest-empty or cached payload fast; no naked busy hang without degraded marker when executor saturated.
4. **Pick scheduler guard** — confirm `pick_scheduler` generation/`is_cancelled` abort before `_save` (L6-002 pattern); add test if gap found.

**FILES (likely):** `server.py`, `internal/learning/dashboard_context.py`, `internal/council/pick_scheduler.py`, `internal/council/daily_pick_engine.py`, `internal/signals/routes.py`, `tests/test_api_handler_timeouts.py`, `tests/test_homepage_pick_read_only.py`

**AC:** targeted pytest green; `test_endpoint_contract.py` green; draft PR + Ditto report (`grok-p3a-council-signals-report-2026-10-06`); no deploy; no `fly.toml` / `RESOLVER_*` env bumps.

**Reference:** `cursor-agents-communication/g0-1058-composer-p1-handoff.md` §A–C (occupancy root cause — do not re-score on GET).

## P3a report (DONE)

- **PR:** https://github.com/cryptoreporthub/subnet-dashboard/pull/1330
- **head:** `7adfafd8`
- **tests:** P3a targeted suite (`test_api_handler_timeouts`, `test_daily_pick_meta`, `test_daily_picks_lock`, `test_fast_shell_context`, `test_homepage_pick_read_only`, `test_prod_stability`, `test_scheduler_submit_guards`, `test_signal_pipeline`, `test_signals_outcome_hardening`) → **242 passed, 3 failed** — failures **pre-existing on `main`**: `test_prod_stability` message-intel + mindmap health-block (order-flaky); `test_signals_outcome_hardening::test_outcome_progress_callback_touches_between_work`. `test_endpoint_contract.py` → **148 passed** (env: `SIGNALS_FRESHNESS_SECONDS=99999999`, `PYTHONPATH=.`).
- **code review:** `_pick_sections` read-only (cache + `_find_today(_load())`); plain GET `/api/signals` serves stale cache + background refresh (no inline regen); `_simivision_weighing_rows_cached` non-blocking lock; emergency home prime no-join; pick scheduler `is_cancelled` wired via `_work_generation` (L6-002 test added). Daily-pick hydrate GET meta/stale on main — verified, not regressed.
- **MC verdict:** **PASS** — Ready for review (Grok undrafted early; MC confirms undraft OK)

---

## P2 report (DONE)

- **PR:** https://github.com/cryptoreporthub/subnet-dashboard/pull/1328
- **head:** `a862121d`
- **artifacts:** `audit-kit/evidence/f02-static-rerun-receipt-2026-10-06.md`, `audit-kit/evidence/f02-gate-c-prod-env-receipt-2026-10-06.md`
- **AC review:** docs-only (2 files, +109 lines); audit pin `ce3d8200…` correct; static sweep re-verified (58 matches, exit 0); Gate C env receipt PARTIAL PASS with honest NOT_OBSERVABLE fences for silent guard knobs
- **MC verdict:** **PASS** — Ready for review

## P1 report (DONE)

- **PR:** https://github.com/cryptoreporthub/subnet-dashboard/pull/1326
- **head:** `7c020112`
- **MC verdict:** PASS — Ready for review

## P4a report (DONE)

- **PR:** https://github.com/cryptoreporthub/subnet-dashboard/pull/1327
- **head:** `f4ae56b5`
- **tests:** `test_resolver_revive` + `test_phase3_mid_guards_orphan_revive` + `test_resolver_scheduler` → **56 passed, 2 failed** (legacy `test_revive_recycles_hung_scheduler_and_runs_once`, `test_revive_honest_when_tick_fresh` — **pre-existing on `main`**, not P4a regressions); P4a AC tests (`test_revive_after_cycle_timeout_not_tick_in_progress`, `test_revive_honest_tick_in_progress_when_live_cycle_young`, `test_force_release_cycle_lock_replaces_wedged_lock`) **all passed**; `test_endpoint_contract.py` → **148 passed**
- **code review:** timeout releases `_cycle_lock` via `_force_release_cycle_lock`; revive recycles stale lock via `_resolver_cycle_lock_stale` (no blind `tick_in_progress`); no `RESOLVER_*` env bumps in diff
- **MC verdict:** **PASS** — Ready for review
