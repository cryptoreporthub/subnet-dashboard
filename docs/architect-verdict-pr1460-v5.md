# Architect verdict on PR 1460, revision 5

Supersedes revision 4. Revision 1 is what was posted at #1460 (issuecomment-6261292438). This is a review of the packet `docs/Ditto-Cap-Telegram-report101826.md`, not a design document. Pin `3a65d34ac46a28395559310f21db013b4581c645`. Packet head `e4272bccdc917712c3afae39c516c1c70955eaa2`. Prod was `357980b4` when last verified (2026-10-19). Nothing in this verdict is implemented, deployed or pushed by the author.

The verdict that follows is Claude Code's. It folds in the second-pass corrections from the exchange on #1460 (the reply that accepted the freshness-gate amendment and retracted three numbers). Where a number appears, it carries a tag:

- **R** receipt: code read at a pinned SHA, a command run, or a live fetch.
- **M** memory or another agent's claim.
- **D** derived arithmetic.
- **L** local or synthetic.

A cap or timeout that was tuned against a degraded system proves only what the constant is, not what the system needs.

## What changed from revision 4

1. **Freshness gate added, in the same unit as #1443.** Accepted. See item 6 below.
2. **The membership freeze is not released by the TTL in normal operation.** Age is measured from `build_started_at` (`internal/council/score_snapshots.py:104-119`), so every successful 30 minute build resets it. `rank_subnets_by_snapshot` returns `None` only past the TTL (`:246-248`). Scored names carry their score and beat the `-1.0` sentinel (`:263-268`). While builds succeed the scored set never changes, at any TTL value. Halving the TTL does not double the reshuffle rate. It only brings the blank page sooner after an outage. The sentinel fix is the only change that alters membership in healthy operation. **R**.
3. **Three numbers are withdrawn.**
   - The **165** in `membership_admitted_count` is not the active universe. Prod `/api/subnets` (166 rows, 2026-10-19) has 129 rows with `status: active` and `source: taomarketcap` (root plus netuids 1 to 128, no gaps). The other 37 rows (netuid 129 and 131 to 167) have `source: none` and no price, stake or emission. `is_tradable_subnet` only tests `netuid > 0` (`internal/subnets/tradable.py:28-31`), so they count as admitted. Active N is about 128. **R**.
   - **"40 of 128 ever scored, 31 of the true top 40 never reached"** is not a measurement. The simulation seeds with the 40 lowest netuids and never admits an unscored name, so "40 ever scored" restates the assumption. Chance alone misses about 27.5 of the true top 40. The mechanism is confirmed in code. The magnitude in prod is unmeasured. **L**.
   - **The "about 1.4%" hoisted share** is not a result. The numerator is a synthetic 19.5 ms per name measured locally with the hoist. The denominator is the prod 1.44 s per name measured before the hoist, so it still contains the cost it is compared against. Do not quote it. **L, D**.
4. **A statement in revision 4 is corrected.** Revision 4 said the hoist already removes the per-subnet Telegram cost. It removes the per-subnet DB read. The per-subnet 3000-row pass stays.
5. **The 37 slots make `capped_out` and `complete` misleading.** `capped_out` 125 is 88 real names plus 37 slots, and `coverage.complete` cannot become true while slots count in the denominator. Not yet traced: why the membership no-shrink rule keeps them, and whether a cap-free build would spend scoring time on them. Fix #1461 (registration read from chain) is the proposed route, and it is a separate release.
6. **Two caps differ by design drift.** The scheduler cap is 20, but `_subnets_for_pick_creation` (`internal/council/daily_pick_engine.py:205-206`) gives 24 with the env unset, and `POLICY_SCHEDULER_24` in `internal/council/pick_selection_audit.py` (built from `_scheduler_cap_limit()`, `:57-60`) replays 24 while the scheduler ran 20. Mechanism confirmed. Whether any audit result changes is not traced. **R**.
7. **`fly.toml:89` sets the snapshot cap to 40.** An earlier "0 or 40" reading was wrong. **R**.

## Rule applied to every number

A number counts only with a receipt. Everything else is a claim and is labelled as one.

## Findings carried from revision 4

- The 805 ms Telegram cost is a local prototype figure, and "32.2 s, 55.8% of the build" is multiplication (40 x 0.805 s). The only prod receipts are build totals: 53.06, 54.30, 57.36 and 57.70 s over 40 names, one of which I read myself (54.30 s, cycle `run_at` 2026-10-19T09:11:28Z). **M, D**.
- The starvation finding is verified independently at the pin: the sort key at `score_snapshots.py:268` returns `-1.0` for unscored names. **R**.
- The repo's own verdict doc says "Caps are not unnecessary on prod today", written with the hoist absent. Ditto's later split is Claim A (Telegram is dead weight, supported) and Claim B (the full universe fits, gated on a measurement nobody has taken).
- Prod metrics were unreliable on 2026-10-18 (gauges read 0 when a key was missing, age gauges pinned). Any `/metrics` figure from that window is suspect. The `/api/learning/health` cycle block carries its own `run_at` and is not a pinned gauge.
- The 3000-row query cap was born with the Telegram feature (2026-08-07) as a memory bound, with no recorded reason for 3000. Topology is one machine, one volume, one web process. `fly.worker-v2.toml` is the parked split, not prod.

## Verdict

1. **Measure first, on a healthy build.** Nothing about caps, timeouts or gates changes until a post-deploy reading exists. That means deploying #1443 together with its fixes (#1464, #1465, and the rollout items #1462, #1463). Deploy approval is the repo owner's alone. "Healthy" must be defined before measuring, for example a stretch with no health-check failures and no OOM kills. The owner has not set that.
2. **Telegram scoring path: DELETE**, on structural grounds only (dead capability, council to message-intel coupling, a 43-reference public response field, data at rest in stored picks). The cost argument rests on a model and is not used.
3. **Cap plumbing: REPLACE** with a `Selection` value carrying a named `NO_LIMIT` and identity-carrying `dropped`, with a `limit < N` test on both paths. A `Dropped` reason that no HTTP response carries is the defect #1464 had with `shortlist_status`, so the reason must reach a response.
4. **Starvation sentinel fix first and blocking**, then the hunt-band limit (cold start only).
5. **Constants.** The 8 s, 90 s, 480 or 600 s, 20, 24, 40 and 3000 values are not carried forward on authority. Each is re-derived on a healthy build or deleted. The deadline policy is read once from config at the process boundary and handed down, not rebuilt as a constant per call site. The 5.3x multiplier is a gate to be measured, not a premise.
6. **Freshness gate ships in the same unit as #1443.** A stale or missing snapshot must be served with an explicit stale label and its age, not replaced by an empty payload. Remaining request-path scoring (`/api/top-pick/hour`, the SSR `_pick_sections`) is removed in that unit or listed as a known gap.
7. **Snapshot cap.** Not changed until the post-deploy read exists. The profile doc's four gates are hypotheses from a degraded window. The end state is the full universe with no caps and no scoring on the web request; 40 is a staged first step.
8. **One ordered plan in the packet.** Part VI, Part VII and Part I change 6 currently give different orders. The packet should carry one. Fix A alone (without the ordering it depends on) is a regression, and that hazard should be load-bearing in the plan.
9. **Pre-flight must write both branches.** If `TELEGRAM_EVIDENCE_CALIBRATION` was ever set in the Fly env, neutral replay is not a valid proof. The history may be unanswerable, so both outcomes are written now.
10. **Architect skill.** Re-run only when post-deploy numbers exist and a structural choice remains, for example whether the hourly pick should read the snapshot.

## What would make me scrap this

- Post-deploy per-name cost stays near 1.3 s. Then the Telegram read was not the main term and the 13x gap with the picker (13.87 s over 128 names, `82c51651`, **M**) sits elsewhere.
- The pick replay differs after the `Selection` swap.
- Snapshot reads on the request path misbehave on a stale snapshot.

## Open questions for the owner

- What counts as "healthy enough to measure"?
- Is the 2026-09-17 fabricated-citations thread the event the owner meant? Not confirmed.
- Approval to deploy #1443 and its fixes is the owner's alone.

## Unverified

- Fly secrets and any env override of the cap defaults beyond the names-only secrets check (which found neither `SCORE_SNAPSHOT_SCORE_WORKERS` nor `SCORE_SNAPSHOT_MAX_SUBNETS`).
- The origin and meaning of 480 versus the code default 600, and of the 90 s tick.
- Whether `select_hourly_pick` goes through the hoist.
- Real `_conviction_rows` cost on prod; the 5.3x multiplier at two values of N; whether anything client-side reads `telegram_evidence_calibration`.
- Packet Part V and the Part III patch sketches.
