# P0-A universe-filter decision gate

**Recorded:** 2026-08-24 during Implementation Directive v2.1.
**Membership changes:** none. Product choice (display-only vs true feed exclusion) is still a human decision.

Frozen set under investigation: `{75, 80, 87, 90, 118}`.
2026-08-12 top-20 mcap drop list (product request): `{64, 51, 4, 44, 120, 95, 9, 53, 8, 3, 68, 107, 75, 28, 56, 5, 34, 62, 19, 14}`.

## Exact current filter

**Confirmed from code.** [`internal/live_subnets.py`](../internal/live_subnets.py) `_registry_netuids()` returns sorted unique netuids from `_registry_list()` with **no** exclusion list, rank, market-cap, emission, or stake threshold. It feeds chain fetch only (`get_subnet_price_rows` / `get_all_subnet_data`). `config/registry.json` is gitignored and absent in this checkout.

Pump scan universe is **not** `_registry_netuids()`. It is `load_subnets_for_pump_signals()` → `fetch_all_subnet_signals()`, which prefers merged cache → TMC → merge. Rows with `netuid is None` are dropped; there is no tradable/top-N/mcap filter on that path.

[`internal/chain_client.py`](../internal/chain_client.py) `get_all_netuids()` uses `list(range(min(total, MAX_NETUIDS)))` with `MAX_NETUIDS=200` — a **range clip**, not a drop list. If upstream `subnet_getN`/`total` is ~75, the range is `0..74` and **excludes 75/80/87/90/118**.

[`fly.toml`](../fly.toml) comments a “75-subnet price batch” tied to `LIVE_SUBNETS_BATCH_DEADLINE_SECONDS` / Blockmachine RPC timeouts (2026-08-12), not a pinned netuid drop list.

[`internal/subnets/scoring_cap.py`](../internal/subnets/scoring_cap.py) excludes mega `marketcap_rank` names from the **heuristic scoring hunt pool**. That is a separate universe from pump `signal_rows`.

## Historical commit (Aug 10–19)

**Confirmed from code (git log).**

- `internal/live_subnets.py` commits in window: 2026-08-12 sync-wedge/deadline/partial-results and 2026-08-13 resolver/registry-gated boot. **No** drop-list introduction.
- `internal/pump/signals.py` / `taostats_overlay.py`: **no** commits 2026-08-16–18.
- Freeze window 2026-08-16–18: only `a8fd21e7` 2026-08-18 “restore stable inline Fly topology” (`fly.toml`). **After** freeze ~2026-08-17T14:09Z.
- Verbatim 20-netuid drop list: **not present** in committed Python/JSON/MD (git grep null).

**Null result (reportable):** no Aug 16–18 commit on `live_subnets.py` or `signals.py`. Timing does **not** prove a same-day code change caused the freeze. Env/config, upstream `total≈75`, or sticky merged/TMC cache remain open.

## Dynamic vs pinned

**Confirmed from code:** `_registry_netuids()` is dynamic (whatever is in the runtime registry file). Pump feed is dynamic (whatever the preferred source list returns). The 20-netuid drop list is **not** pinned in this tree. Scoring-cap mega skip is dynamic by rank, not a frozen id list.

## Overlap with frozen netuids

**Confirmed from code:** SN75 **is** on the 2026-08-12 product drop list; `{80, 87, 90, 118}` **are not**. Exclusion of those four cannot be that pinned list alone.

**Inferred pending evidence:** strongest mechanism that explains all five (all ≥75) plus `scanned:75` is a **~75-row source / `range(total≈75)` clip**, optionally plus pump preferring merged/TMC over the registry path `/api/subnets` uses on timeout.

## Count vs membership

**Confirmed from code:** matching count (~75 scanned vs ~75 live batch) does **not** prove matching membership. `scanned` is `len(signal_rows)`, not “all tracked ladder keys were visited.”

**Inferred pending runtime:** frozen membership `{75,80,87,90,118}` vs scanned population `0..74` (if range clip) would be disjoint. Falsifiable prediction still needs prod `jq`: every frozen netuid ≥75 **and** every netuid <75 is fresh. Any fresh row >74 or stale row <75 breaks simple range-clip.

## Registry vs pump

**Confirmed from code:** **not the same filter.** `/api/subnets` timeout path uses `registry_subnet_rows()` + name enrich. Pump uses `load_subnets_for_pump_signals()`. Divergence is possible (and expected if TMC/merged omit high netuids while registry still lists them).

## Production evidence

**Confirmed from runtime (prior probes, not re-run here):** scheduler alive; `scanned:75`; five alerts frozen at `2026-08-17T14:09Z`; SN118 had ladder transitions through 2026-07-31.

**Inferred pending evidence:** whether registry still contains those five; whether BM `total≈75`; whether pump is on merged/TMC vs live for those scans.

## Decision

Do **not** change feed membership in this PR. Ship additive coverage/age meta so “ok scan” cannot hide stalled rows. Human still chooses display-only exclusion vs true feed exclusion vs leave as-is once prod `jq` lands.
