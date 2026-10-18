# Candle / price-history source for universe forward labels

Status: spike note (read-only). No production code changed. Branch `claude/candle-source-spike`.
Evidence tags: **measured** (this spike, raw RPC or repo files read), **inferred** (derived from measured values), **guess** (not checked).

## Recommendation

1. **Label source = on-chain pool price, sampled live.** Price = `SubnetTAO / SubnetAlphaIn` (TAO per alpha), which equals `swap_currentAlphaPrice` (see facts 1-2). Sample every 5 minutes (the existing forward-recorder cadence, `TICK_INTERVAL_SECONDS = 300`). Each tick reads all subnets in one storage batch.
2. **Provider order:** Finney first, Blockmachine (BM) second, per the owner's rule. Finney cannot serve state more than about 200 blocks (about 40 min) back, so Finney is only usable for live reads at the tick. BM is the only one of the two that served history at 1 h, 1 d, 7 d and 30 d, and a ~34-day-old fixture block.
3. **Historical base rate:** backfill from BM only, paced. Not measured in this spike.
4. **Do not use `data/price_cache.json` for labels.** It is TAO/USD times one alpha snapshot per subnet, and its newest candle is 2026-08-14 (about 9 weeks old).
5. **Units:** label in TAO terms (alpha/TAO). A USD label mixes in the TAO/USD move, which is not the subnet's move.

## Endpoints (hostnames only, no keys)

- Blockmachine: `rpc.blockmachine.io` (repo default, `BLOCKMACHINE_RPC_URL`). **measured**
- Finney: the repo reads `FINNEY_RPC_URL` (`internal/chain_price/config.py`), which is unset in this sandbox. The production value is not in the repo and was not read. This spike probed the public `entrypoint-finney.opentensor.ai`. **measured** for that host; the prod Finney host is **unverified**.

## Measured facts

1. **Price formula.** Fixture block (`tests/fixtures/chain/bm_9060887.json`, 385-key batch): for netuid 1 and 64, `SubnetTAO / SubnetAlphaIn` equals `swap_currentAlphaPrice / 1e9` at the printed precision (0.0% difference). **measured** (offline decode)
2. **Live match.** At head and at each live depth (1 h, 1 d, 7 d, 30 d) on BM, the netuid-64 ratio equals spot / 1e9 to 9 significant digits. **measured**, 4 points
3. **Storage schema.** `SubnetTAO`, `SubnetAlphaIn`, `NetworkRegisteredAt` per netuid, `Timestamp.Now` in the same batch, and `NetworksAdded` for membership, all read as the repo expects. A 385-key batch covers 128 netuids at one block. **measured**
4. **BM history.** Served with block-pinned responses (`block` field equals the requested hash) at 300, 7 200, 50 400 and 216 000 blocks back. Also served the fixture block about 34 days old: 385/385 storage rows matched the recorded values. **measured**
5. **Finney history.** Served at head, at 5, 60 and about 150-200 blocks back. **Error 4003 "State already discarded"** at 300 blocks back (about 1 h). Boundary between about 200 and 300 blocks. **measured** (boundary **inferred**)
6. **Block time.** BM: 300 blocks = 3 600.0 s; 216 000 blocks = 2 594 844 s, about 12.01 s per block over 30 days. **measured**
7. **Rate limits.** 38 requests in about 3 minutes, 1.5 s spacing, zero 429s, zero `Retry-After` headers, zero non-200 HTTP responses (one JSON-RPC error 4003 on Finney, fact 5). Latency 0.4-1.1 s. **measured**, but this sample does not establish the limit.
8. **Repo price cache.** `data/price_cache.json`: 179 entries; 129 subnet candle series, all `source: taomarketcap` (derived), hourly, 168 bars each. Aligned timestamps: a subnet's close divided by netuid 1's close has coefficient of variation about 1e-4 to 1e-3, so every subnet is the same TAO/USD curve times one constant (`_derive_subnet_candles` in `internal/indicators/price_fetcher.py`). Newest candle 2026-08-14; the probe date was 2026-10-18. **measured**
9. **Gecko config.** `config/price_pairs.json` maps 100 of 129 subnets to a GeckoTerminal pool, but the committed cache holds no Gecko entries. Live Gecko coverage was **not measured**.

## Request budget (per endpoint)

| Job | Requests | Notes |
|---|---|---|
| Forward tick (5 min) | 2 | `chain_getFinalizedHead` + one 385-key batch. Works for any subnet count up to the batch size. |
| + spot cross-check | +2 | The sampler checks 2 netuids per tick (`_crosscheck_netuids`). Measured divergence is zero, so this doubles the cost for no new information. Keep it only if the guard is wanted. |
| Membership refresh | ~1/day | `state_getKeysPaged` on `NetworksAdded`. |
| Forward, 30 days, 5 min | ~17 300 (2/tick) or ~34 600 (4/tick) | About 577 requests/day at 2/tick. |
| Backfill, per sampled point | 2 | `chain_getBlockHash` + one batch. |
| Backfill, 30 days at 1 h / 15 min / 5 min | 1 440 / 5 760 / 17 280 | BM only. |

**Feasibility (inferred):** the forward tick is about 0.4 requests/min per endpoint, well below any public limit I know of (**guess**). Backfill at 5 min needs about 17 300 requests; at 1 request/s that is about 5 hours. Either is feasible if BM's real limit is near 1 request/s (**unverified**).

## Peak-touch vs close-to-close

`forward_label` in `internal/learning/universe_labels.py` is close-to-close at the endpoint. "+2% within 1h" needs a touch rule. Five-minute ticks (12 per hour) see only the sampled points, so they **underestimate** intra-bar touches. A true touch rule needs finer data or a stated tolerance. **inferred**

## Unverified

- The production `FINNEY_RPC_URL` host, and whether it is an archive node (not read; no Fly secrets read).
- BM and Finney rate limits beyond 38 requests. Whether BM retains beyond about 34 days.
- Finney's exact retention boundary (between about 200 and 300 blocks).
- The finalized-head lag relative to the unfinalized head (not measured).
- Live Gecko coverage and rate limits. The repo notes a taostats free tier of 5 calls/min (`fetchers/taostats_client.py`); not checked.
- The base rate of +2% within 1 h. **Not measured.** It needs a backfill of roughly 1 440 requests (1 h close) to 17 300 (5 min touch) on BM.
- Whether the dynamic-TAO price formula is `TAO/alpha` in every runtime version. Checked only against the BM runtime that served this probe.
- `bittensor` runtime metadata: the repo has no copy, and the package is not installed here, so decoding relied on keys copied from the fixtures.
