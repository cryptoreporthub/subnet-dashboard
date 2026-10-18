# Score store and per-cycle budget (design, not implemented)

Status: proposal. Replaces the count caps (20, 24, 40, 75) with a freshness contract.
Owner issue: #1372. Measurements it depends on: `claude/build-cost-instrumentation` on #1443.

## Why not a count

A count cap makes the scored set a function of the previous cycle's ranking, so a name that was not scored last cycle stays unscored (F45 in the root-cause report). It also makes coverage depend on a clipped denominator. The owner's acceptance criteria in #1372 reject both.

Cost is not stable enough to pick a count. Day scoring for 40 names took 548 s (10/12), 2,647 s (10/15) and 57.4 s (10/17). No single build size can be gated on that.

## Data shape

- `ScoreRecord` keyed by `(netuid, horizon)`:
  - `score`, `components`
  - `scored_at` (UTC)
  - `inputs_fingerprint` (hash of the market row, pump state version, calibration version)
  - `status` in {`ok`, `failed`, `excluded`}
  - `reason` when status is not `ok`
- `Membership`: the authoritative active set, with `fetched_at` and `source`. Root and deregistered rows are excluded before membership is built. A membership that is stale or from a degraded source is not usable, and the store does not certify coverage from it.

## Per-cycle work

- Each cycle takes a fixed time budget (`SCORE_CYCLE_BUDGET_SECONDS`, initial value set from #1443's measured per-name cost).
- The cycle scores names in order of `scored_at`, oldest first, with never-scored names first. It stops when the budget is spent.
- Cost variance changes how fast coverage converges. It does not make a cycle fail. A slow cycle leaves more names stale, and that shows up in the coverage metric.
- Parallelism inside a cycle is bounded by the existing worker setting. It does not change the budget rule.

## Coverage states

Per netuid in membership:
- `fresh`: `scored_at` within `SCORE_FRESH_CYCLES` cycles
- `stale`: scored before that, not yet re-scored
- `never`: no record
- `failed`: last attempt failed (reason stored)
- `excluded`: not tradable (no price or no volume), with the reason

Snapshot completeness is `fresh / membership_size`. A snapshot with any `never` or `failed` name is not complete. The denominator is always the authoritative membership, never a clipped list.

## Request-path contract

- Handlers (`/api/top-picks`, `/api/top-pick/hour`, `/api/daily-pick/weighed`) read the store only.
- A cold store returns an explicit `status: "warming"` shape. The handler never scores inline. This is the change in #1442.

## Gates before any count is removed

The count envs and the 20/24/40/75 literals are removed in one change, and only after:
1. The store is live on prod and `coverage_fraction` has reached 1.0 at least once.
2. Per-cycle budget is set from measured per-name cost in the build-cost counters.
3. Peak RSS of a full cycle is measured from the process, not a scrape sample.
4. Rate-limit responses during a cycle are counted and stay within the existing cooldown behavior.

## Not resolved by this design

- Why day scoring took 2,647 s on 10/15. The build-cost counters are the instrument for that. The design does not depend on the cause, but the budget size does.
- Whether the calibration context is hoisted on prod. #1443 does it. This design assumes it.

## Migration order

1. Land #1443 and the build-cost counters (measurement and request-path reads).
2. Add the store alongside the current snapshot. Write both. Read the store on request paths.
3. Switch the scheduler to the budget rule. Keep the snapshot as the publish artifact until coverage reaches 1.0.
4. Remove the count envs and literals in one change, after the gates above.
