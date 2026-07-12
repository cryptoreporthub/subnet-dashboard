# PR #113 vs #115 audit (read-only, Phase L)

**Date:** 2026-07-12  
**Branches:** `cursor/phase-l-signals-alerts-b061` (#113) vs `cursor/phase-l-signal-pipeline-b061` (#115)

## Overlap
- `internal/signals/store.py`, `pipeline.py`, `routes.py` — both implement signals + alerts + WS
- #113 uses `POST /api/alerts/subscribe` only; assignment requires `POST /api/alerts` for alert rows
- #113 embeds SELL>HOT in pipeline; slice 4 extracts `internal/signals/rules.py`

## Adopted from #113 (adapted, not duplicated wholesale)
- `AlertEngine` threshold checks + webhook dispatch
- `SignalBroadcastHub` + `/ws/signals` lifecycle
- `append_many` → changed-signals list for alert fan-out

## #115-only (kept)
- Slice 1 route shapes (`since` query, `appended` meta)
- Explicit `rules.py` for precedence + dedup
- `POST /api/alerts` body validation + preserve-existing-store semantics
- `build_signals_context()` wired in `server.py` only

## Do not merge #113 as-is
Would conflict with merged `main` signals router and duplicate slice 1 tests.
