# Intel-loop v2.1 — implementation report

**Branch:** `cursor/intel-loop-v21-f6eb` @ `6ccfdd9ee7557c8627e540afc95de6db23043642`  
**Evidence mix:** Confirmed from code | Confirmed from tests | Confirmed from runtime (prod Fly + local :5000) | Browser Gemini (local)

Membership of the pump feed was **not** changed. Pump scan loop was **not** restarted. Telegram listener was **not** enabled. Inline-worker topology was **not** changed. Existing API field names were **not** removed.

## What shipped

| ID | Change |
|---|---|
| P0-A gate | `docs/intel-loop-p0a-universe-gate.md` — no membership edit |
| P0-A obs | Ladder `meta`: `signal_row_count`, `missing_from_feed` (bounded), `missing_from_feed_count`, `max_row_age_seconds`, `feed_stalled`, `tracked_subnet_count`. `GET /api/pump-ladder/state?summary=1` drops per-row `transitions`. `status` stays `success`. |
| P0-B | Additive `generated_at`, `max_row_age_seconds`, `data_available`, `freshness`, `freshness_scope`. `_mark_stale` still maps timeout/error/unavailable → `ok` but keeps `prior_status` and sets `freshness=stale`. Handler timeout/error with rows is `freshness=stale` (`handler`), not `fresh`. Hard timeout JSON is stamped. Persist-TTL path stamps **row** age. Shared SSR/API payload. Visible banner on `/pump` SSR plus a banner-only hydrate update from those API fields (directive allowed banner after API fields; not a data-path rewrite). |
| P0-C | `/listener` remains 308 → `/subnetsummer`. Context catches non-timeout failures. Outer try around context **and** `TemplateResponse`. Honest fallback HTML. Conviction coerced to float in feed/trending/mi rows; Jinja uses `|float` + jury numeric guard. |
| P1 | `/api/subnets` `meta` keeps `status` (top-level). Adds `handler_status`, `enrichment_status`, `generated_at`, `data_available`. Registry fallback nulls missing emission/stake/apy instead of `0.0`. Universe vs timeout stay separate. |
| P2 | `docs/intel-loop-p2-telegram-listener.md` — document only. |
| Live omission | Split-v2 circuit-open `GET /api/pump-alerts` stub in `WorkerVolumeProxyMiddleware` now `attach_pump_freshness(handler_stale=True)`. `status` stays `degraded`. Independent of `/api/subnets` timeout. |

## Tests (confirmed from tests)

`PYTHONPATH=. pytest tests/test_intel_loop_v21.py tests/test_pump_desk_payload.py tests/test_subnets_source_meta.py tests/test_summers_telegram_desk.py tests/test_pump_alert.py::test_api_pump_alerts_route tests/test_worker_volume_proxy.py` → **62 passed**. Luna SHIP on `6ccfdd9e`.

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
| Client hydrate | Isolation via `allSettled` + per-section catch | Home `living_focus` TypeError is **independent** of pump banner / summer 500 | Gemini local browser | Banner-only hydrate; did **not** batch-fix living_focus | Warm vs cold same; no “no client defects” claim |

## Five conclusion buckets

1. **Client / runtime hydration** — local Gemini: `/` 200 with independent `living_focus` TypeError. `/pump` 200; screenshot shows orange **Pump rows unavailable** plus empty counts; a later walkthrough video shows Pump desk BUILDING Apex without that banner in-frame (do not treat the video as banner proof). `/listener` 308 → `/subnetsummer` 200 (local only). **Not** a “no client defects” claim. Prod UI not re-run.
2. **Server freshness** — Fly `GET /api/pump-alerts` still `status:success` with five rows `updated_at` 2026-08-17T14:09Z (honesty fields absent on **main**). Local branch stamps freshness. Split-v2 degraded stub stamps stale without rewriting `degraded`.
3. **API status / enrichment** — Fly `/api/subnets?limit=500` 200, `status:timeout`, `meta.source:registry`, **n=75 min=0 max=74**, frozen `{75,80,87,90,118}` **absent**. Local adds `handler_status`/`enrichment_status`. Independently convergent vs pump `status:success`.
4. **Historical universe filter** — **unconfirmed as a committed drop list.** Membership **unchanged** this PR. Strongest live evidence: registry universe `0..74` vs ladder keys `0..199` still holding frozen ids. Human decision: display-only vs true exclusion vs leave-as-is.
5. **Unresolved** — Fly `/subnetsummer` still **500** (`Internal Server Error`); which env disables Telegram; deploy of #1034; worker heartbeat/volume writability not visible on local UI.

## Non-claims

- Did not restart the pump scan loop.
- Did not enable Telegram.
- Did not declare full pytest green.
- Did not treat HTTP 200 or `status:success` as proof of hydration or freshness.
