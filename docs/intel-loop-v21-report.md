# Intel-loop v2.1 — implementation report

**Branch:** `cursor/intel-loop-v21-f6eb`  
**Evidence mix:** Confirmed from code | Confirmed from tests | Confirmed from runtime (prior prod probes) | Inferred pending evidence | Browser pending

Membership of the pump feed was **not** changed. Pump scan loop was **not** restarted. Telegram listener was **not** enabled. Inline-worker topology was **not** changed. Existing API field names were **not** removed.

## What shipped

| ID | Change |
|---|---|
| P0-A gate | `docs/intel-loop-p0a-universe-gate.md` — no membership edit |
| P0-A obs | Ladder `meta`: `signal_row_count`, `missing_from_feed` (bounded), `missing_from_feed_count`, `max_row_age_seconds`, `feed_stalled`, `tracked_subnet_count`. `GET /api/pump-ladder/state?summary=1` drops per-row `transitions`. `status` stays `success`. |
| P0-B | Additive `generated_at`, `max_row_age_seconds`, `data_available`, `freshness`, `freshness_scope`. `_mark_stale` still maps timeout/error/unavailable → `ok` but keeps `prior_status` and sets `freshness=stale`. Persist-TTL path stamps **row** age, not payload TTL. SSR + `/api/pump-alerts` share `load_pump_alerts_desk_payload`. Visible banner on `/pump` + hydrate. |
| P0-C | `/listener` remains 308 → `/subnetsummer`. Context catches non-timeout failures. Outer try around context **and** `TemplateResponse`. Honest fallback HTML. Conviction coerced to float in feed/trending/mi rows; Jinja uses `|float` + jury numeric guard. |
| P1 | `/api/subnets` `meta` keeps `status` (top-level). Adds `handler_status`, `enrichment_status`, `generated_at`, `data_available`. Registry fallback nulls missing emission/stake/apy instead of `0.0`. Universe vs timeout stay separate. |
| P2 | `docs/intel-loop-p2-telegram-listener.md` — document only. |

## Tests (confirmed from tests)

`PYTHONPATH=. pytest tests/test_intel_loop_v21.py tests/test_pump_desk_payload.py tests/test_subnets_source_meta.py tests/test_summers_telegram_desk.py` → **23 passed**.

Not a full-suite claim. `server_original` / unported modules remain out of scope.

## Surfaces

| Surface | Observed | Root cause / hypothesis | Evidence tier | Fix or next | Remaining uncertainty |
|---|---|---|---|---|---|
| Pump ladder scan | Scheduler alive; `scanned:75`; five names frozen 2026-08-17T14:09Z | Feed gap: those netuids absent from `signal_rows`. Strongest code fit: `get_all_netuids()` `range(min(total,200))` if `total≈75` | Runtime (prior) + code | Observability only; **no** membership change | Prod `jq` of `/api/subnets` vs ladder keys vs `signal_rows`; any fresh >74 or stale <75 falsifies range-clip |
| `/api/pump-alerts` `status:success` | Rows exist, timestamps Aug 17 | Status is row-count, not age. Persist 600s TTL is payload age | Code + tests | Additive freshness; UI banner | Prod body after deploy |
| `_mark_stale` | timeout/error/unavailable → `ok` | Launder without freshness | Code + tests | `prior_status` + `freshness=stale` | Client still paints non-timeout statuses; banner is the honesty path |
| `/api/subnets` `meta` timeout + zeros | Full registry on 3s timeout | Handler timeout ≠ universe filter; enrich names only, 0.0 looked live | Code | handler vs enrichment vs generated_at; null missing metrics on fallback | Live 0.0 vs missing 0.0 on **live** path not rewritten |
| `/subnetsummer` 500 | Bare 500; `/listener` 308 | Render/conviction Undefined, not load-shed 503; Telegram disabled is env | Code + local repro class | Outer fallback + float coerce | Fly traceback pin if logs exist |
| Telegram `enabled:false` | Config `reason:disabled` | fly.toml `auto` overridden by process env | Code | Document only | Which Fly secret/process env is `off` |
| Client hydrate | Isolation via `allSettled` + per-section catch | Does **not** prove no client bugs | Code trace only | No client defect claim | **Browser pending** (Gemini not in this agent catalog) |

## Five conclusion buckets

1. **Client / runtime hydration** — not verified in a browser this run. No “no client defects” claim. Isolation in JS is necessary but not sufficient.
2. **Server freshness** — `status:success`/`ok` can coexist with stale rows. Additive `freshness` + banner is the honesty path. Shared SSR/API payload.
3. **API status / enrichment** — `/api/subnets` timeout is handler-budget + registry fallback, **not** proven as the universe filter. Missing emission/stake on that fallback is now `null`.
4. **Historical universe filter** — **unconfirmed as a committed drop list.** `_registry_netuids()` has no exclusion list. Pump ≠ registry. Verbatim 20-id list not in tree. SN75 is on the 2026-08-12 product mcap list; `{80,87,90,118}` are not. Null git result Aug 16–18 on `live_subnets.py`/`signals.py`. Range-clip remains the strongest **hypothesis**.
5. **Unresolved** — Gemini browser (cold/warm `/`, `/pump`, `/listener`, `/subnetsummer`, Network bodies, DOM, worker heartbeat, volume writability); Fly `/subnetsummer` traceback; prod netuid membership `jq`; which env disables the listener.

## Non-claims

- Did not restart the pump scan loop.
- Did not enable Telegram.
- Did not declare full pytest green.
- Did not treat HTTP 200 or `status:success` as proof of hydration or freshness.
