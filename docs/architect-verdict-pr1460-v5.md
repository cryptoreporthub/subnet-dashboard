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
   - The **165** in `membership_admitted_count` is not the active universe. Prod `/api/subnets` (166 rows, 2026-10-19) has 129 rows with `status: active` and `source: taomarketcap` (root plus netuids 1 to 128, no gaps). The other 37 rows (netuid 129 and 131 to 167) have `source: none` and no price, stake or emission. `is_tradable_subnet` only tests `netuid > 0` (`internal/subnets/tradable.py:28-31`), so they count as admitted. Active N is about 128. Two receipts: my fetch of 2026-10-19 and Ditto's independent fetch of 2026-10-20T02:08:56Z (166 total, 129 active, 37 `source: none` at 129 and 131 to 167, 128 taomarketcap rows above netuid 0). Prod `/version` was still `357980b4` for both. `membership_admitted_count` 165 is therefore 128 real names plus 37 slots, so the figure I withdrew is the admission count, not the universe. The receipt's own `expected_netuids` list is empty in `/api/learning/health`, so 165 = 128 + 37 is arithmetic from `/api/subnets` plus the timing block. **R, D**.
   - **"40 of 128 ever scored, 31 of the true top 40 never reached"** is not a measurement. The simulation seeds with the 40 lowest netuids and never admits an unscored name, so "40 ever scored" restates the assumption. Chance alone misses about 27.5 of the true top 40. The mechanism is confirmed in code. The magnitude in prod is unmeasured. **L**.
   - **The "about 1.4%" hoisted share** is not a result. The numerator is a synthetic 19.5 ms per name measured locally with the hoist. The denominator is the prod 1.44 s per name measured before the hoist, so it still contains the cost it is compared against. Do not quote it. **L, D**.
4. **A statement in revision 4 is corrected.** Revision 4 said the hoist already removes the per-subnet Telegram cost. It removes the per-subnet DB read. The per-subnet 3000-row pass stays.
5. **`coverage.complete` is false on two independent gates.** `complete` is `published and membership_ok and horizons_complete and capped_out == 0` (`internal/council/snapshot_coverage.py:354-359`), and the scored-complete check also needs the succeeded set to equal the expected set, where `membership_scoring_expected` is every membership netuid above 0 (`:100-102`). With 125 dropped names, `complete` is false on the cap gate alone, before the 37 slots enter. The 37 slots then inflate the denominator: `capped_out` 125 is 88 real names plus 37 slots. Baseline for the post-deploy read, from the live block on 2026-10-20 (receipt: Ditto, `/api/learning/health` run_at 2026-10-20T01:39:30Z): count 40, `capped_out` 125, `coverage.complete` false. Not yet traced: why the membership no-shrink rule keeps the slots, and whether a cap-free build would spend scoring time on them. #1461 (registration read from chain) is the proposed route and is a separate release. **R**.
6. **The scheduler and the pick-creation path cap differently, by a different mechanism than I first wrote.** All three sites read the same variable with the same default: `PICK_SCHEDULER_UNIVERSE_CAP`, default 24 (`internal/council/pick_scheduler.py:32`, `internal/council/daily_pick_engine.py:209`, and `_scheduler_cap_limit()` at `internal/council/pick_selection_audit.py:57-60`). The difference is the other operand of the `min`. The scheduler takes `TOP_SCORING_UNIVERSE` from `server` (`server.py:647`, default 20) at `pick_scheduler.py:157`, giving `min(24, 20)` = 20. The pick-creation path and the audit read the raw env with a default of 40, giving `min(24, 40)` = 24. So the drift is 20 versus 24, and the constant to fix is the `TOP_SCORING_UNIVERSE` default, not `PICK_SCHEDULER_UNIVERSE_CAP`. Neither variable is declared in `fly.toml`, so 20 is the code default unless a Fly secret overrides it (not checked). Whether any audit result changes is not traced. **R**.
7. **`fly.toml:89` sets the snapshot cap to 40.** An earlier "0 or 40" reading was wrong. **R**.

## Line citations

Every line citation in this document was re-derived with `git show 3a65d34a:<path>` against the pin SHA, not a branch: `tradable.py:28-31`, `daily_pick_engine.py:205-209`, `pick_selection_audit.py:57-60`, `fly.toml:89` (`SCORE_SNAPSHOT_MAX_SUBNETS`) and `:90` (`SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS`), `score_snapshots.py:246` (TTL check) and `:268` (the `-1.0` sentinel), `snapshot_coverage.py:100-102` and `:354-359`, `server.py:647`, `pick_scheduler.py:32,157`. Ditto's review of `f340f54d` gave line numbers uniformly 5 higher in five files (for example `fly.toml:94`, `tradable.py:33-36`). I checked `fly.toml` on the #1464 and #1465 branches and `SCORE_SNAPSHOT_MAX_SUBNETS` is still at line 89 there, so those PRs do not explain the offset, and I do not know what Ditto read. A reader should confirm each citation with `git show 3a65d34a:<path>` rather than from a branch or working tree. **R**.

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
- Closed: `internal/council/hourly_pick.py` at the pin has no `telegram`, `message_intel`, `evidence` or `calibration` reference, so the hourly path does not read Telegram evidence and the hoist question has no referent. Caveat: I read that module, not everything it imports. **R**.
- Real `_conviction_rows` cost on prod; the 5.3x multiplier at two values of N; client reads of `telegram_evidence_calibration`: a code search at the pin finds no hit in `static/` or `templates/`, and the reads found are server-side (`internal/council/pick_explain.py`, `daily_pick.py`, `state_vector.py`, `message_intel/calibration.py`). That narrows the question; it does not prove it.
- Packet Part V and the Part III patch sketches.
