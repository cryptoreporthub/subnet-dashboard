---
cursor:
  subagentId: "bc-2b73b904-2901-50eb-9140-0a0daddb3cc1"
---

# Scoring caps — deep profile

**Code pin (investigation):** `ef234c95aa227c21318dd7292ad8228003495589`  
**Draft branch:** `cursor/scoring-profile-2b73` (supersedes snapshot-read work from #1442)  
**Prod deploy (read-only):** Fly release **v2391**, image `deployment-01M559K90411PHFM28DNN362BZ`, machine `7841024b3712e8` (1024MB, sjc). Last confirmed deploy SHA from Actions: **`ef234c95`** (2026-10-17T20:28Z). `/version` and `/metrics` intermittently **timeout** during this run (health check **critical**); numbers below combine **2026-10-17 ~21:50Z scrape** + Fly status.

## Hoist on prod?

| Mechanism | On `ef234c95` prod? | Evidence |
|-----------|----------------------|----------|
| Telegram `_conviction_rows` + `calibration_health` **once per batch** | **No** | `build_full_universe_snapshot` only hoisted `pump_ladder_state`; `daily_pick.py` hoists for picks only (`scoring_context` added on draft branch) |
| `calibration_health_snapshot` reuse | **No** | `calibration_for_subnet` recomputed health every call until draft branch |
| Scenario `get_scenarios(300)` once per batch | **No** | `memory_scoring.scenario_outcome_adjustment` called per subnet until draft branch |

**Ditto `ec3c24cc` claim (805 ms → 0.2 ms/name):** Mechanism confirmed locally — **not** deployed on prod at `ef234c95`.

### How much of **1.44 s/name** (57.7 s ÷ 40) does missing hoist explain?

| Model | Math | Wall for 40 names |
|-------|------|-------------------|
| Measured local (TELEGRAM=on, **50 ms** mocked `_conviction_rows` per call, no hoist) | 40 × 52 ms | **2.06 s** (0.052 s/name) |
| Ditto extreme ( **805 ms** per `_conviction_rows` ) | 40 × 0.805 s | **32.2 s** |
| Observed prod build | 57.7 s | **1.44 s/name** |

**Explain-the-number:** If prod SQLite + message_intel volume makes `_conviction_rows` ~**0.8–1.0 s** (not the sandbox empty DB), missing hoist alone is **~32–40 s** of the **57.7 s** build (~55–70%). Remainder: pump overlay on full ladder, soul_map/weights, GIL-bound Python, **serial** scoring loop, **shared RPC cooldown** with live hydrate/stake/price jobs, CPU throttle on shared-cpu-2x.

---

## Prod vs local gap

| Factor | Prod (~1.44 s/name) | Local harness (~0.0005 s/name, 128 tradable) | Citation |
|--------|---------------------|-----------------------------------------------|----------|
| Telegram calibration DB read | Per subnet → `_conviction_rows` (3000-row join) | Empty/no DB; patch shows **2.06 s / 40** at 50 ms/read | `calibration.py:194-247`, `rollup.py:1066-1088` |
| Scoring concurrency | **Serial** `for` loop | Draft: `SCORE_SNAPSHOT_SCORE_WORKERS` (default 4) | `score_snapshots.py:449-520` (pre-draft serial) |
| Pump ladder | Loaded from **volume** (`load_state`) | Empty `pump_keys=0` in sandbox | `score_snapshots.py:400-408` |
| Registry / hydrate | Worker `SCORE_SNAPSHOT_REGISTRY_ONLY=on` + membership prep | `load_subnets_for_display` emergency registry | `score_snapshots.py:549-619` |
| OHLCV / indicators | `allow_hydration=False` on day score (cache-only) but **cold cache on volume** | No price_cache file | `state_vector.py:1818-1824` |
| RPC 429 / cooldown | Shared endpoint lock | No RPC in thin local score | `chain_client.py:55-86`, `_RL_LOCK` |

**Attack-the-premise:** Local **0.35 s/name** (Joshua reference) still **4× faster** than prod 1.44 s/name but **100× slower** than our registry sandbox — sandbox is **not** prod-shaped until Telegram DB + pump volume + RPC contention are present.

---

## RPC, 429, and shared budget (prod read-only)

**Scrape (2026-10-17 ~21:50Z, when `/metrics` responded):**

| Metric | Value |
|--------|-------|
| `subnet_score_snapshot_build_wall_seconds` | **57.70** |
| `process_resident_memory_bytes` | **~413 MB** |
| `chain_rpc_requests_total{endpoint="rpc.blockmachine.io",method="chain_getBlockHash",outcome="ok"}` | **251** |
| Same, `outcome="rate_limited"` | **44** |
| Same, `outcome="cooldown_skip"` | *(not in excerpt; counter exists in code)* |

**429 cooldown model (code, not per-cycle trace):** `note_rate_limit` sets endpoint-wide cooldown default **60 s**, doubling up to **3600 s** (`chain_client.py:71-86`). **Cannot** sum wall-clock cooldown per snapshot cycle from counters alone (process-lifetime totals). **44** rate-limited RPCs since boot ⇒ non-zero shared pressure.

**Finney vs Blockmachine:** OHLCV chain path uses **Blockmachine** (`price_fetcher.py:55-264`). `FINNEY_RPC_URL` is optional in `chain_price/config.py:76-84` for bracketed resolve — **not** wired into snapshot day scoring. Fan-out to Finney for snapshot would **split** rate limits but adds **consistency risk** (price source divergence); **not enabled** on draft branch.

**Shared locks / budget:** `ChainClient` uses global `_RL_LOCK` / `_RL_UNTIL` per endpoint — **stake scan, live subnets batch, price fetcher, judges** contend on same Blockmachine host. `heavy_job_slot` serializes named jobs (`heavy_job_gate.py:24-62`); logs show `score_snapshot` acquire/release — **one snapshot writer** vs other heavy work on **single web machine**.

**Prod py-spy:** **Skipped** — no read-only attach API without machine console; would require operator SSH. Documented only.

---

## Serial vs parallel scoring (code)

| Path | Model | Location |
|------|--------|----------|
| Snapshot day build (prod) | **Serial** for-loop | `score_snapshots.py` ~449 (main `ef234c95`) |
| Snapshot day build (draft) | **Parallel** `ThreadPoolExecutor`, `SCORE_SNAPSHOT_SCORE_WORKERS` default **4**, hour scoring stays serial | `score_snapshots.py` + env |
| Request `score_universe` | Serial for-loop | `score_cache.py:72-77` |
| Daily pick scoring | `ThreadPoolExecutor` in `select_daily_pick` | `daily_pick.py` (pool) |

---

## Cheap wins implemented (draft branch)

1. **`enrich_scoring_market_context`** — hoist `_conviction_rows`, `calibration_health`, `scenario_memory_scenarios` once (`scoring_context.py`).
2. **`calibration_health_snapshot`** param on `calibration_for_subnet` (`calibration.py`, `state_vector.py`).
3. **Bounded parallel snapshot scoring** — `SCORE_SNAPSHOT_SCORE_WORKERS=4`.
4. **Snapshot read APIs** — `/api/top-picks` off `score_universe` (#1442 carry).

**Not implemented (risk / scope):** RPC batching refactor; Finney fan-out for OHLCV; removing `SCORE_SNAPSHOT_MAX_SUBNETS` on prod.

---

## Harness measurements (NOT `REGISTRY_ONLY` flag; tradable registry + pump fixture + hoist)

Environment: `SCORE_SNAPSHOT_REGISTRY_ONLY=off`, `enrich_scoring_market_context`, `_conviction_rows` patched to `[]`, **128** tradable rows, `score_hour=False`, 2026-10-17 UTC sandbox.

| Config | N | Wall (s) | s/name | Peak RSS (MB) | `day_scoring_seconds` | Workers |
|--------|---|----------|--------|---------------|----------------------|---------|
| Hoist + serial | 128 | **0.068** | 0.0005 | 85.7 | 0.067 | 1 |
| Hoist + parallel | 128 | **0.061** | 0.0005 | 85.7 | 0.111* | 4 |

\*`day_scoring_seconds` sums per-thread CPU; wall is lower — **GIL-bound**, modest win locally.

| Telegram hoist simulation (TELEGRAM=on, **50 ms** `_conviction_rows`/call) | N=40 | Wall |
|-------------------------------------------------------------------------------|------|------|
| No hoist (per-subnet load) | 40 | **2.06 s** (0.052 s/name) |
| With hoist | 40 | **0.01 s** |

**RPC call count / 429 in harness:** **0** (no live RPC in scoring loop with cache-only indicators).

**Projected prod after hoist only (conservative):** If conviction read was **~0.8 s × 40 = 32 s**, build drops **57.7 → ~26 s** (~0.65 s/name) — still above 8 s handler budget if moved to request path; **caps still needed** until full membership + parallel + cache warmth proven.

---

## Dead work audit (file:line)

| Issue | Location | Impact |
|-------|----------|--------|
| Hour scores **copied from day** (no hour pass) | `score_snapshots.py:510-516` | Saves 2× CPU when `SCORE_SNAPSHOT_SCORE_HOUR=off` (prod default) |
| **Rank cap** before score (`SCORE_SNAPSHOT_MAX_SUBNETS=40`) | `score_snapshots.py:627-636`, `fly.toml:89` | 40 scored, not 127+ |
| **Registry-only** subnet load on worker | `score_snapshots.py:549-560` | Skips live hydrate for membership (feeds cap selection) |
| Repeated `calibration_health` on same rows (pre-draft) | `calibration.py:247-248` | O(subnets × rows) CPU |
| `scenario_memory.get_scenarios(300)` per subnet (pre-draft) | `memory_scoring.py:76-78` | O(subnets × 300) scan |
| `pump_ladder_state` load once per build | `score_snapshots.py:400-408` | Good |
| No `get_subnet()` in snapshot loop | — | N/A (not found on hot path) |

---

## `SCORE_SNAPSHOT_MAX_SUBNETS=40` after fixes?

**Verdict:** **Raise only after read-only prod proves:**

1. `subnet_score_snapshot_coverage_complete == 1` for a full cycle at trial cap (e.g. 80 then 127).
2. `subnet_score_snapshot_build_wall_seconds` × (`N/40`) **<** `SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS` (480) with headroom.
3. `process_resident_memory_bytes` **< ~900 MB** on 1 GB VM during build.
4. `chain_rpc_requests_total{outcome="rate_limited"}` rate not climbing during build window.

**Draft branch does not change cap=40** — structural fixes first.
