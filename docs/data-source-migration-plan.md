# Data Source Migration Plan (Grok 4.7)

**Date:** 2026-09-25  
**Status:** Phase 1 in progress  
**Supersedes:** Any “freeze at 24/40” directive — those caps are migration oracles only.

## Problem statement

The dashboard still treats TaoMarketCap (TMC) as the hot-path primary for council picks when the shared universe snapshot is cold. Blockmachine (BM) already powers `live_subnets` background sync but is not wired into `get_council_subnet_feed()`. Meanwhile, scoring depends heavily on `price_change_*`, `market_cap`, and `marketcap_rank` — fields TMC supplies today and BM does not natively expose.

Separately, universe **scoring caps** (20/24/40) were OOM-era workarounds. Prod benchmark (2026-09-24, forked Fly volume, `shared-cpu-2x`/1GB) showed cap128 scoring at ~14s wall, 214MB peak RSS, no OOM. The effective prod cap is often **20** (`min(PICK_SCHEDULER_UNIVERSE_CAP=24, TOP_SCORING_UNIVERSE=20)`). Target end state: **full eligible universe** scored in background `score_snapshots`; request handlers score zero inline.

## Layer model (target)

| Layer | Role | Source |
|-------|------|--------|
| L1 Primary | Live price, pool, stake, emission, swap volume | Blockmachine RPC (`internal/chain_client.py`) |
| L2 Supplement | Fear/greed, seven-day prices, rare derived metrics | TaoStats (rate-limited, cached) |
| L3 Fallback | Display metadata, cold-start overlay | TaoMarketCap + `config/registry.json` |
| L4 Local | `price_change_*`, derived rank/mcap from BM samples | `internal/subnets/price_history.py` |

## Field matrix (scoring / picks)

| Field | Used by | Current source | BM replacement | Gap / fallback |
|-------|---------|----------------|----------------|----------------|
| `price` | state_vector, red_team, signals | TMC / BM lite | BM `get_alpha_price` | None |
| `price_change_24h` | state_vector, rotation, alerts, recovery | TMC | Local history samples | Compute from BM sync; TMC overlay when cold |
| `price_change_7d` | state_vector, brain_letter, recovery | TMC | Local history (7d lookback) | Same |
| `price_change_30d` | state_vector, recovery | TMC | Local history (30d lookback) | Same |
| `volume` / `buy_volume_24h` | red_team, scoring_cap activity | BM swap deltas / TMC | BM `get_swap_volume` | Lite fetch may omit volume until full sync |
| `market_cap` | state_vector, scoring_cap | TMC | `price × total_alpha` proxy | Imperfect vs TMC; rank order matters more |
| `marketcap_rank` | scoring_cap mega/mid hunt | TMC | Derived sort on proxy mcap | Keep TMC rank as diagnostic during migration |
| `emission`, `stake` | state_vector, simivision | BM / TMC | BM RPC | None |
| `name` | UI, picks | registry + TMC | `enrich_subnet_row` (registry) | Not BM `SN{n}` on hot path |
| OHLCV candles | indicators, RSI in state_vector | TMC `price_fetcher` | BM-derived from TAO candles × alpha | Phase 4 |
| `fear_and_greed` | judges (optional) | TaoStats | No BM equivalent | TaoStats only |

## Phased implementation

### Phase 1 — BM-first feed + local deltas (this branch)

1. **`internal/subnets/price_history.py`** — record BM price on each `live_subnets` sync; compute `price_change_24h/7d/30d`; derive `market_cap` proxy and `marketcap_rank`.
2. **`internal/live_subnets.py`** — call `price_history` after successful sync; enrich merged rows before cache write.
3. **`internal/subnets/feed.py`** — load order: universe snapshot → BM `live_subnets.json` cache → TMC network (unchanged timeout/fallback).
4. Tests for price history math and feed tier order.

**Does not change:** pick scheduler caps, `TOP_SCORING_UNIVERSE`, or published pick contract.

### Phase 2 — Universe snapshot enrichment

1. **`subnet_universe._build_rows`** — overlay BM live cache fields over TMC rows (price, volume, computed deltas).
2. Fix **`MAX_NETUIDS=200` sort-truncate** — replace with explicit cap telemetry + no silent drop (separate PR if large).
3. Label `emergency_registry` honestly in feed meta.

### Phase 3 — Full eligible universe scoring

1. Background worker scores **all eligible netuids** in `score_snapshots` (remove `SCORE_SNAPSHOT_MAX_SUBNETS=40` as effective ceiling after gate).
2. API read paths use snapshot ranks only — **zero inline scoring**.
3. Retain cap20/24/40 as **audit replay oracles** in `pick_selection_audit.py` during migration window.
4. Gates before contract change:
   - Full scheduler tick timing (not just `select_daily_pick` wall)
   - One cold-cache prod run
   - Compare picks vs oracle caps for 7 days

### Phase 4 — Indicators / OHLCV

1. Flip `price_fetcher` priority: BM-derived candles first, TMC fallback.
2. Optional TaoStats enrichment for non-critical fields.

## What we are NOT doing

- Freezing `PICK_SCHEDULER_UNIVERSE_CAP=24` or `TOP_SCORING_UNIVERSE=40` as product policy.
- Treating `TAOSTATS_MERGE_LIMIT=24` as universe cap (it is judges/pump TaoStats call budget, hard-clamped to 5).
- Removing TMC entirely — it remains L3 fallback and migration comparison.

## Verification

| Check | Command / artifact |
|-------|-------------------|
| Feed prefers BM cache | `tests/test_data_source_feed.py` |
| Price deltas | `tests/test_price_history.py` |
| Contract guard | `pytest tests/test_endpoint_contract.py` |
| Prod cap benchmark | `scripts/benchmark_universe_cap.py` on Fly forked volume |

## Decision log

- **2026-09-24:** Prod benchmark falsifies OOM rationale for cap128 on current VM class.
- **2026-09-25:** User + Ditto afternoon position — full eligible universe canonical; caps are oracles.
- **2026-09-25:** Phase 1 implementation started on `cursor/data-source-migration-bf32`.
