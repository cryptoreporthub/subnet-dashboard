# Root-cause review — PRs #1357 and #1358 (2026-10-12)

Review lane: read-only analysis at pinned heads; verdicts also posted as PR comments.
- PR #1357 @ `d433e35907dff177291f1f4708c351e24602847d` (`cursor/prod-wedge-heavy-job-live-subnets-0979`)
- PR #1358 @ `efd62d116ae3257658524820967e2951fb7f6fd7` (`cursor/phase1-snapshot-coverage-cfe8`)
- Base: `main` @ `2ff85cc2`. Prod: still `5d840ba4` (both PRs undeployed). Drafts; no merge/deploy; Joshua GO gate.
- Comments: [#1357](https://github.com/cryptoreporthub/subnet-dashboard/pull/1357#issuecomment-6121291663) · [#1358](https://github.com/cryptoreporthub/subnet-dashboard/pull/1358#issuecomment-6121295166).

**Verdict: both PRs address the verified root causes, not bandaids.** Each maps a verified causal link to a structural change; the old bandaids are removed, not stacked upon. Two named residuals per PR are non-blocking.

---

## PR #1357 — killable spawn child + lite FETCH_MODE (prod wedge)

### Verified root cause (prod, 2026-10-11, machine 7841024b3712e8)
The web process ran the live_subnets chain fetch **in-process on daemon threads with no batch deadline**:

1. On RPC degradation, `get_subnet_price_rows`'s `as_completed` waited on **all** futures with no wall-clock cap → the fetch thread stuck.
2. CPython cannot kill a thread, so main's thread-alive **wedge guard** (`live_subnets.py:220` on main) could only *skip* subsequent syncs — it could not remove the stuck thread.
3. The stuck thread (plus web + inline essential worker) starved the event loop on the 1GB VM → `/health` HTTP 000, Fly machine check critical.
4. `prediction_resolver heavy_job_slot ~1034s` in the same incident was **downstream starvation**: the resolver already has `_run_refresh_cycle_with_timeout`, orphan-thread handling, and cycle-lock wedge release. Symptom, not an independent cause.

### Cause → fix mapping (verified in code @ d433e359)
| Causal link | Fix | Where |
|---|---|---|
| Unkillable stuck thread | Fetch moved to a **spawned child process** (spawn ctx; fork only under pytest) — processes *can* be terminated | `live_subnets.py::_fetch_chain_data`, `_terminate_fetch_process` (terminate → grace → kill, plus re-kill in `finally`) |
| Unbounded `as_completed` wait (the trigger) | Absolute `LIVE_SUBNETS_BATCH_DEADLINE_MONOTONIC` enforced **inside** the batch loop: 0.25s slices, `fut.cancel()`, `shutdown(wait=False, cancel_futures=True)`, bounded thread joins | `chain_client.py ~578-611` |
| Parent could wait forever | Recv bounded by `rpc_deadline`; `spawn_grace` covers only the ready handshake; deadline send has its own 5s cap | `live_subnets.py ~203-290` |
| Wedge vector moved into IPC | Length-prefixed framed IPC; select + non-blocking read/write, EAGAIN looped to deadline, 8MB payload cap | `live_subnets_ipc.py` |
| Child returning too late | `batch_deadline = rpc_deadline − LIVE_SUBNETS_RPC_RETURN_MARGIN_SECONDS` (3s, floor 0.5s) so executor shutdown + framed send fit the parent window | `live_subnets_fetch_child.py` |
| Old bandaid (thread-alive wedge guard) | **Removed**; overlap handled by `_sync_lock` non-blocking acquire; failure fail-closed via `live_subnets_boot.json` status | `live_subnets.py::_sync_once` |

### Not a data regression
`FETCH_MODE=lite` is already main's default (`os.environ.get("LIVE_SUBNETS_FETCH_MODE", "lite")` on main) — the PR does not shrink the fetched set further; it makes the existing lite path deadline-bound. `LIVE_SUBNETS_BATCH_DEADLINE_SECONDS=85` (fly.toml) is correctly documented as the no-parent-clock upper bound; prod path is 90s − setup − margin.

### Residuals (non-blocking)
- **R1:** lite price rows omit stake/emission/volume vs `get_all_subnet_data`. Pre-existing on main, but fly.toml now pins it permanently — confirm no consumer needs those fields from the live cache, or document the trade.
- **R2:** the resolver slot hold is untouched — correct (downstream symptom; resolver has its own timeout), but the merge summary should say so explicitly so a future `heavy_job_slot … held_ms` line isn't misread as "unfixed".

### Gates
Replit re-spot + Joshua GO; prod soak on the 1GB VM (spawn child ~20–42MB RSS measured) is the remaining real-world proof.

---

## PR #1358 — score snapshot coverage honesty

### Verified root cause
Coverage "complete" was computed against a **shrunken denominator** (`tradable ∩ membership`), so missing subnets were structurally invisible — `complete=true` could be reported while subnets were absent from scoring. The measurement defect, not snapshot staleness, is what masked partial snapshots (PR #1292 / SMOKE-001 class).

### Cause → fix mapping (verified @ efd62d11)
1. **Denominator pinned at the source:** `membership_scoring_expected()` = full membership (>0), "never tradable∩shrink"; `score_snapshots.py:411-426` pins the membership receipt **before** scoring. `scoring_expected_netuids` is a backward-compat alias with the same honest denominator; no consumer of the old shrink remains in the coverage path.
2. **Honest gates:** `missing_not_admitted` (expected−tradable), `unaccounted` (expected−succeeded−failed); `complete` requires `succeeded == expected` AND both empty AND `membership_allows_complete` AND `capped_out == 0` (`snapshot_coverage.py:203-211`). `TOP_SCORING_UNIVERSE=40` therefore forces `complete=false` in prod — the metric working as intended.
3. **Fail-closed membership:** `refresh_incomplete` → `membership_ok=false`.
4. **Consumers:** `/metrics` gauges read the on-disk snapshot (worker/web are separate processes) with `subnet_score_snapshot_age_seconds` + `SCORE_SNAPSHOT_MAX_AGE_SECONDS=7200` staleness gate — no silent stale reads.
5. Capture deadline checked **after** receipt + coverage assembly; `build_coverage_block` failure cannot block publish after save.

### Why not a bandaid
Metric semantics change at the source: the tradable set is now an *input to missing-classification*, not the denominator. The scoring cap itself is deliberately unchanged ("no scoring cap / membership policy change") — that policy work is the already-planned Phase 2; the honest denominator is its prerequisite, not its replacement.

### Residuals (non-blocking)
- **R1:** PR body pins evidence at `3875bffa` but the head is `efd62d11` — refresh the body/evidence pointer so receipts match the merge head.
- **R2:** `root_netuid_in_scoring_set` is still a constant `False` (scoring_set excludes ≤0) — compute it or drop the field.
- **R3:** the stale-metrics test does not assert the age gauge value.

### Gates
Replit re-spot + Joshua GO. Draft; no deploy.
