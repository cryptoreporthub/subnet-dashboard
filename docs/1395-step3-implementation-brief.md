# #1395 Step 3 — implementation brief (historical backfill + bracketed block resolve)

**Audience:** Agent B implementer. **Baseline:** `origin/main` @ **`562982ba`** (prod deploy vehicle #1409; Step 2 merged `ed478a3b` / PR #1406). **Prod posture:** `CHAIN_PRICE_FORWARD_RECORD` remains **off** unless Joshua explicitly scopes a flip.

## Goal (Step 3 only)

1. **Historical backfill** ≤ ~30d into `data/chain_prices.db`: hourly-aligned `chain_sampled` rows with the same provenance schema as Step 2 forward ticks (`block_hash`, `series_key`, `provider`, `quality`, `schema_version=2`).
2. **Bracketed / anchored `resolve_block_at`**: Step 2 shipped a **fail-closed stepped** search (≤4 rounds, 12s tolerance) tuned for forward-recorder latency. Step 3 adds a **bracketed bisection** path with **anchors** (finalized head, `hint_block`, in-process block cache, optional `chain_blocks` DB rows) and a **higher round budget** for offline backfill — without weakening the default stepped path used by live sampling.
3. **Gecko fallback** only when chain archive cannot serve a bucket (`archive_miss` / `unknown_block` on pinned storage): tag rows distinctly (`quality` / metadata) so Step 4 never treats them as `chain_sampled` truth.

**Not in Step 3:** enable forward recorder in prod; wire `get_chain_bar` into grading; `REFUSE_DERIVED_FOR_GRADING=on` (Step 4 / Agent A).


## Step 2 foundation (do not re-litigate)

| Area | Location | Notes |
|------|----------|--------|
| Forward tick | `internal/chain_price/sampler.py` → `run_forward_sample` | `kind=forward`; membership via `get_member_netuids` (`NetworksAdded`) |
| Block → time | `internal/chain_price/block_resolve.py` → `resolve_block_at` | Stepped correction; `_BLOCK_CACHE`; fails closed on unprobed hash |
| Reader / fallback | `internal/chain_price/reader.py`, `config.rpc_provider_endpoints()` | Finney first when `FINNEY_RPC_URL` set, else BM; `provider_served` on writes |
| Persistence | `internal/chain_price/db.py` | `chain_blocks` + `chain_price_samples`; retention 45d / row cap 600k |
| Bars (read-only) | `internal/chain_price/bars.py` → `get_chain_bar` | Not wired to grading |

**Live evidence (Step 2 review, still relevant):** public Finney HTTPS **discards state** at ~30d fixture block; BM retains. Backfill must **fail over** on `archive_miss` per provider, not silently use head.


## Scope — files to add or change

### A. Bracketed `resolve_block_at` (library)

**File:** `internal/chain_price/block_resolve.py`

- Add parameters (names illustrative; keep backward-compatible defaults):
  - `search: Literal["stepped", "bracketed"] = "stepped"` — stepped = current behavior.
  - `max_rounds: int | None` — default `_MAX_ROUNDS` (4) for stepped; **16–20** for bracketed backfill.
  - `anchor_blocks: Optional[Iterable[int]]` — extra probes seeded before bisection (`hint_block`, cached blocks, DB anchors).
- **Bracketed algorithm (sketch):**
  1. Probe finalized **head** → upper anchor `(high, ts_high)`.
  2. Seed **lower anchor** from `max(0, high - WINDOW)` or nearest `chain_blocks` row with `ts_ms <= target`.
  3. Maintain monotone bracket on block number using probed `(block, ts_ms)` pairs; **bisect** mid-block until `|ts - target| <= _TOLERANCE_MS` or rounds exhausted.
  4. **Stall / gap:** if target `ts_ms` falls strictly between two probed timestamps with no block in between (synthetic stall test in `test_block_resolve_convergence_1406.py`), return `(None, None, "invalid")` — same fail-closed contract as Step 2.
  5. Timestamp reads still go through `ChainReader` / `_block_ts_via_reader` so provider fallback matches storage reads.
- **Optional:** `load_anchors_from_db(ts_ms, window_ms, db_path)` in `db.py` — `SELECT block, block_hash, ts_ms FROM chain_blocks WHERE ts_ms BETWEEN ? AND ? ORDER BY ts_ms` (cheap; forward ticks populate over time).

**Tests:** extend `tests/test_block_resolve_convergence_1406.py` with `search="bracketed", max_rounds=18` — same convergence cases; add one case that **stepped** exhausts at 4 rounds but **bracketed** succeeds (seed from step2 review: `seed=6, jitter=3000` target).

### B. Historical sample at pinned block (shared with forward)

**File:** `internal/chain_price/sampler.py` (or new `historical.py` if sampler grows)

- Extract **`sample_at_block_hash(reader, block_hash, block_number, *, write, kind)`** from `run_forward_sample` body: membership → `state_queryStorageAt` reserves → spot cross-check on 2 netuids → `_parse_storage_batch` → `insert_*`.
- `run_forward_sample` calls the helper with `pin_finalized_head()`; backfill calls it after `resolve_block_at(..., search="bracketed")`.

**`chain_blocks.kind`:** add `backfill` (constant `_KIND_BACKFILL`); forward stays `forward`.

### C. Backfill orchestration

**New:** `internal/chain_price/backfill.py`

- `plan_hourly_bucket_ts_ms(end_ms, days=30) -> list[int]` — UTC hour buckets (align with Step 1 Gecko comparison: hourly).
- `backfill_bucket(reader, bucket_ts_ms, *, db_path, dry_run, gecko_fallback)` → per-bucket result dict (`outcome`, `block`, `samples_written`, `fallback: gecko_pool | None`).
- **Idempotency:** rely on `INSERT OR IGNORE` PKs; skip bucket when a non-disputed `chain_sampled` row exists for that hour (query by `ts_ms` window or `chain_blocks.bucket_ts`).
- **Rate budget (from Step 1):** default **≥1.5s sleep** between buckets; env `CHAIN_PRICE_BACKFILL_SLEEP_S`; cap burst RPC (~5–8 calls/bucket × ~720 buckets ≈ 3.6k–5.8k calls — run once on Fly machine or operator laptop, not in web process).
- **Membership:** always `get_member_netuids` at pinned hash — **never** admit netuids from price probe alone (#1396).

**New:** `scripts/backfill_chain_prices.py`

- CLI: `--days 30`, `--dry-run`, `--db-path`, `--end-ts` (optional), `--max-buckets N` (smoke), `--search bracketed`.
- No FastAPI route; **no** `tests/test_endpoint_contract.py` change unless a route is added (not expected).

### D. Gecko fallback (#1397 interaction)

**Do not** use broken Gecko OHLCV for backfill validation until #1397 lands.

- **Merge order:** **#1397 before** enabling gecko fallback in backfill (or gate fallback behind `price_fetcher` fix).
- Fallback shape: for mapped pools in `config/price_pairs.json`, fetch hourly close at bucket time with **`currency=token`**, write rows with `quality="gecko_pool"` (or separate `price_source` if schema extended — prefer `quality` + documented enum in `outcomes.py`).
- Unmapped netuids: skip bucket subnet or leave hole (log `archive_miss`); no derived TAO×alpha.

### E. #1396 (membership placeholder)

Step 2 sampler **already** uses `NetworksAdded` for forward/backfill membership. **Remaining #1396 scope** is `internal/subnet_universe.py` / `ChainClient.get_all_netuids` probe fallback — **Agent A**.

| Step 3 requirement | Owner |
|--------------------|--------|
| Backfill / sampler never use price-only membership | Agent B (this PR) |
| Universe JSON / `get_all_netuids` probe path | Agent A (#1396 PR) |

Coordinate: no change to `get_subnet_price_rows_batch` (#1363).


## Tests (minimum)

| Test file | What |
|-----------|------|
| `tests/test_block_resolve_convergence_1406.py` | Bracketed mode + anchor seeding; stall gap still `invalid` |
| `tests/test_chain_price_backfill_step3.py` (new) | `plan_hourly_*` count; dry-run backfill against fixture client + tmp db; idempotent second run writes 0 |
| `tests/test_chain_price_step2.py` | Regression — stepped default unchanged |
| `tests/test_endpoint_contract.py` | Run unchanged (no new routes) |

Offline fixture: extend or reuse `tests/fixtures/chain/bm_9060887.json` for one historical bucket; optional second fixture block for spec change depth (Step 2 review item — add when bracketed backfill touches old runtime).


## Falsifiers (must fail loudly)

1. **Unprobed block/hash pair** returned after exhausted search (Step 2 regression).
2. **`state_queryStorageAt` block field ≠ pinned hash** → no rows persisted (Step 2).
3. **Finney primary returns `archive_miss`** on historical hash → reader retries BM; if both miss, bucket outcome ≠ `ok` and no fake `chain_sampled` row.
4. **Netuid 129 / 0** admitted via `swap_currentAlphaPrice` alone in backfill path.
5. **Gecko fallback** without `currency=token` (should be impossible after #1397).
6. **Prod flag:** merging Step 3 does not set `CHAIN_PRICE_FORWARD_RECORD=on` in `fly.toml` / deploy docs.


## Out of scope

- `CHAIN_PRICE_FORWARD_RECORD=on` in prod (Joshua + ops).
- `REFUSE_DERIVED_FOR_GRADING=on` / `price_reference.py` wiring (Step 4).
- New HTTP API for backfill (operator script only).
- Shrinking `ROW_CAP` / retention without disk sizing sign-off (Step 2 review: ~243 MB for 45d forward; backfill may require **ROW_CAP** bump or shorter `--days` — document in PR, do not silently truncate).
- Full Gecko 48h re-validation gate (Step 4); bracketed resolve is a prerequisite re-run, not this PR’s acceptance.


## Suggested PR slices

1. **PR-A (this kickoff):** bracketed `resolve_block_at` + `backfill.py` plan/dry-run + `scripts/backfill_chain_prices.py` + tests (no live RPC in CI).
2. **PR-B:** `sample_at_block_hash` refactor + real writes + gecko fallback (after #1397).
3. **PR-C (ops):** one-shot runbook in `DEPLOY.md` — Fly `fly machine run` with volume mount, not web boot.


## Recommended merge order vs #1396 / #1397

| Order | Item | Rationale |
|-------|------|-----------|
| **1** | **#1397** — `currency=token` on Gecko OHLCV | Tiny; fixes interim #1377 tier and any backfill Gecko fallback. Low conflict with `chain_price/*`. |
| **2** | **#1396** — universe / `get_all_netuids` membership | Agent A; parallel with Step 3 **PR-A** if touch surfaces differ. **Before Step 4**, not strictly before PR-A. |
| **3** | **#1395 Step 3 PR-A** | Bracketed resolve + backfill scaffold/tests on `562982ba`. |
| **4** | **Step 3 PR-B** | After #1397 if Gecko fallback included. |

Step 2 (#1406) is **merged**; do not reopen unless bracketed change breaks stepped default (guard with explicit `search=` tests).


## Draft GitHub comment for #1395 (do not post unless Joshua says “post comment”)

```markdown
## Step 3 kickoff (post–Step 2 prod `562982ba`)

**Baseline:** `main` @ `562982ba` (Step 2 #1406 + deploy #1409). Forward recorder flag still **off**.

**Step 3 scope:**
- Operator script: hourly backfill ≤30d → `chain_sampled` rows in `chain_prices.db` (`chain_blocks.kind=backfill`).
- **Bracketed/anchored** `resolve_block_at` for offline buckets (Step 2 stepped resolver remains default for forward ticks).
- Archive miss → provider fallback (Finney→BM); Gecko pool fallback only after **#1397** (`currency=token`).

**Out of scope:** prod `CHAIN_PRICE_FORWARD_RECORD`, grading / `REFUSE_DERIVED_FOR_GRADING`.

**Merge order:** #1397 → (parallel #1396) → Step 3 PR-A → Step 3 PR-B with Gecko fallback.

Implementation brief: project store `docs/1395-step3-implementation-brief.md`. Draft PR: https://github.com/cryptoreporthub/subnet-dashboard/pull/1411
```


## Acceptance (Step 3 complete — all slices)

- [ ] One-shot backfill script can fill ≥7d hourly buckets on BM (or archival Finney) in dry-run + live smoke (`--max-buckets 3`) without 5xx.
- [ ] Rows have `chain_sampled` provenance fields matching Step 2; `gecko_pool` only on documented fallback path.
- [ ] Bracketed resolve passes synthetic convergence suite; stepped default unchanged.
- [ ] CI: `tests/test_endpoint_contract.py` + new backfill/resolve tests green.
- [ ] Joshua GO before prod data job or flag flips.
