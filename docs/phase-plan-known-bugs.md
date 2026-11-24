# Phase plan: known-bug program, phase 1

Evidence base: origin/main 2a199aec (checked 2026-11-24), the sweep counts reproduced from the register `docs/bug-sweep.md` and `docs/server-refactor-plan.md` on `origin/claude/keen-goldberg-ud7grj` (commit 73767b2e). The sweep script is not on main yet; step D.1 brings it over.

Verification notes (2026-11-24): the six fault sites and the register counts were checked against origin/main by hand. The file-ownership check changed two points, recorded in section E. `gh api .../pulls/1598 --jq .merged` returns `true`.

## A. Goal

Fix every known bug in subnet-dashboard in a safe order, and get a written, checkable plan for all of them. This phase is the start: land the pending #1598 split stack, fix the six "fix first" faults, stop new instances from entering, and queue the rest behind the server.py refactor.

Landing vehicle: the split stack, not #1578. Confirmed from bases. #1598 (stack 1/8) is merged (checked 2026-11-24). #1599 -> main; #1600 -> split/1578-pr2 (#1599's head); #1601 -> pr3; #1602 -> pr4; #1603 -> pr5; #1604 -> pr6; #1605 -> pr7. Each PR is based on the previous one's head, a chain rooted at main. #1578 is the parent branch (base main, `dirty`). It is not landed itself. Closing it after #1605 lands is an outward action that needs the owner's go-ahead. #1606 targets `cursor/soul-map-write-honesty-unit1-bb47`, not main (checked 2026-11-24 with `gh api repos/cryptoreporthub/subnet-dashboard/pulls/1606`), so merging it would not land on main. It stays HELD, and its merge or retarget is the owner's call.

## B. Definition of done for this phase

1. Stack merged: `for n in 1599 1600 1601 1602 1603 1604 1605; do gh api repos/cryptoreporthub/subnet-dashboard/pulls/$n --jq .merged; done` prints `true` seven times.
2. #1591 merged: `gh api repos/cryptoreporthub/subnet-dashboard/pulls/1591 --jq .merged` prints `true`.
3. Timeout fault gone: `T=$(mktemp) && python scripts/bug_pattern_sweep.py --json "$T" >/dev/null && jq '.timeout_joined_by_with_block|length' "$T"` prints `0`. (`--json` takes an output path, so piping it to `jq` fails.)
4. Timestamp fault gone: same command, key `isoformat_plus_Z_aware`, prints `0`.
5. GET write pinned: deferred to R11, not a phase exit gate. The test `tests/test_top_pick_hour_get_readonly.py` is absent on main and fails until R11 fixes the GET write (step 4 writes it with that fix).
6. Each fault PR: `.venv/bin/python scripts/check_invariants.py --check` reports `0 new`, and `.venv/bin/python -m pytest tests/test_endpoint_contract.py -q` passes.
7. Gate in CI: a new fault instance fails the build. Check: add a throwaway `datetime.now(timezone.utc).isoformat() + "Z"` on a scratch branch; `python scripts/bug_pattern_sweep.py --fail-on` exits non-zero. Remove it and it exits 0.
8. This plan's inventory (C) re-run at phase end with current counts.

## C. Bug inventory (counts rerun at origin/main 2a199aec)

Sweep script is NOT on main (`git show origin/main:scripts/bug_pattern_sweep.py` fails). It lives only on the keen-goldberg branch. Step 1 brings it over.

Fix shape for every class: failing test first, see it fail, fix, see it pass, one small PR per class.

Verified fault sites, read at origin/main (all six still present):

| Site | Line on origin/main |
|---|---|
| `internal/learning/dashboard_context.py:120` | `with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:` then `fut.result(timeout=2.0)` |
| `internal/simivision/chat_service.py:135` | `with ThreadPoolExecutor(max_workers=1) as pool:` then `fut.result(timeout=_INVESTIGATION_TIMEOUT_SEC)` |
| `server.py:837` | `with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:` then `fut.result(timeout=8.0)` |
| `internal/council/state_vector.py:1313` | `"timestamp": _dt.now(_tz.utc).isoformat() + "Z",` |
| `server.py:2802` | `updated_at = datetime.now(timezone.utc).isoformat() + "Z"` |
| `server.py:2405` | `"time": datetime.now(timezone.utc).isoformat() + "Z",` |

| Class | Still present | Count (register -> main) | Owner | Fix shape |
|---|---|---|---|---|
| timeout_joined_by_with_block (D8 server.py:837, D9 dashboard_context.py:120, chat_service.py:135 new) | yes | 3 -> 3 | Own PR now (fault PR F1), before R0. Refactor plan has D8/D9 in R11; pulled forward. | Executor without `with`; `shutdown(wait=False, cancel_futures=True)` in `finally`. Test: a hung worker returns within the timeout plus slack. |
| isoformat_plus_Z_aware (D3) | yes | 3 -> 3 | Fault PR F2, before R0 (plan has R11) | `.isoformat().replace("+00:00", "Z")`. state_vector.py:1313 writes a stored value: grep readers first. |
| GET writes (D2) | yes | 1 known | Test in step 4, fix in R11 | `/api/top-pick/hour` (route at server.py:3386) -> `_ordered_hour_picks` (2873) -> `_record_pick_in_learning_loop` (def at 2709, called at 2931). Line numbers are origin/main 2a199aec. Test: GET leaves the learning loop unchanged. Fails today. |
| route_returns_exception_text | yes | 54 -> 54 | R10 adds `degraded()`; non-server routes after R10 | Log the exception, return a fixed code. learning/routes.py 15 first, then store_routes 8, message_intel 6, analytics 5. |
| silent_except_pass | yes | 225 -> 223 (drift of 2; the register is stale, main is authoritative) | Review queue after R9 | Per site: debug log if the state is legitimate, narrow or fix if it hides a bug. background_boot 17, resolver 17, resolver_scheduler 9 first. resolver_scheduler.py:1156 is held with thread 4534140517. |
| non_atomic_json_dump | yes | 59 -> 59 | Review queue after R9 | Use `internal/file_utils.safe_write_json`; skip sites already writing a temp path. |
| hardcoded_relative_data_path | yes | 133 -> 133 | Review queue after R9 | Route through `DATA_DIR`. |
| file_io_in_async | yes | register said clean -> 3 (analytics/routes.py:94; judges/council_routes.py:450, 523) | New, no owner yet | Register drift. Triage in step 7. |
| D1, D4, D5, D6, D7 | per refactor plan | not swept | R11 | Per the plan's Appendix F. |
| Failing unit tests | yes | 164 at the pre-#1598 baseline -> 160 at the #1578 head 0a7635d5 (the head adds 0 new). Source: local test runs at those two commits during the #1578 triage, not the register. | Not triaged | Triage each failure as its own class before R0. Owner: none yet. |
| judges/postmortems.py:56 invariant hit | yes | 1 | Known gap. No PR, no baseline edit. | None. |

## D. Ordered next steps

1. Add the sweep script and a `--fail-on` mode with a stored baseline of current counts. Status (2026-11-24): local commit `7bfd86f9` on branch `sweep/d1-fail-on` (off origin/main 2a199aec), not pushed. Counts match table C. `--fail-on` exits 0 on main. A staged throwaway `isoformat()+"Z"` makes it exit 1, and it exits 0 after removal. An untracked file does not trip it, because the sweep reads `git ls-files`. The pre-push review passed with nits, and the one docstring nit is applied. Table C's GET-writes row says 1 known, but the sweep reports 0 for `get_route_calls_writer`: the write goes through `_ordered_hour_picks`, not the route body. Record the gap, do not fix the count. Verify: `T=$(mktemp) && python scripts/bug_pattern_sweep.py --json "$T" >/dev/null && jq 'map_values(length)' "$T"` matches the table above; `--fail-on` exits 0 on main. `--fail-on` is not wired into CI, so B7 stays open until it is. Blocked: no. (Baseline = today's counts, so this adds no new failure.)
2. Land #1591 (test-only, "behind", rebase). Verify: its CI green, then `.merged` true. Blocked: no.
3. Review and land #1599 -> #1605 in order, root first, one verified PR at a time per the Shipping playbook. Verify per PR: CI green, `mergeable_state` clean, then `.merged` true; after each merge retarget the next to main. Blocked: no. Risk: server.py overlap with step 4/5 (see F).
4. Test pinning D2: `tests/test_top_pick_hour_get_readonly.py` calls `GET /api/top-pick/hour` and asserts no learning-loop write. Expect it to fail today. Land it as an expected-failure marked test, or hold the failing test inside the R11 PR. Recommend the latter: a red test on main blocks CI. Overlaps #1603, so write it after #1603 merges. Blocked: on #1603.
5. Fault PR F1 (three timeout sites), then F2 (three timestamp sites). Verify: new tests fail before, pass after; sweep keys read 0; step B6 commands. Blocked: no, but start after step 3 to avoid conflicts (recommend; the fixes are 1-line each).
6. Fix route exception text, learning/routes.py first (15), once R10's `degraded()` exists. Blocked: on R10 (R9, and so on R0 to R9).
7. Triage file_io_in_async (3). Verify: each marked fix or accepted in writing. Blocked: no. Result (2026-11-24, read at origin/main 2a199aec, no production data read): all three accepted, no code change. `internal/analytics/routes.py:94` reads a local price-baseline JSON with `open` and `json.load` inside `api_price_tracking_baselines`. `internal/judges/council_routes.py:450` and `:523` read bundled HTML templates inside two page routes. `analytics/routes.py:94` reads the price-baseline file that `message_intel/price_tracker.py` writes. The writer drops entries older than `BASELINE_RETENTION_DAYS = 7` (`price_tracker.py:37`, cutoff at `:525`), so the file is bounded by a 7-day window. The steady-state size per write rate is not measured. The two `council_routes.py` reads are bundled HTML templates with fixed size. Re-triage if the retention cap is removed or raised, or if the file's size or read time is measured as material. The baseline records the count as 3.
8. R0 starts only after #1599 to #1605 have landed and the null-block fix (section E, #1604 at `d3cd254c`) is on main, taking its numbers from main then. Verify: R0's plan checks (route manifest, golden files). Blocked: on #1604 landing.

## E. Blocked items and unblock conditions

- #1606 (HELD): the lens pass is done. Result: PASS-with-nits at `0a7635d5`, no A findings, all 10 lenses loaded. Its one behavior change (APPLIED to DECLINED, below) is not in the PR text. #1606 stays held for the owner's merge call. Its base is `cursor/soul-map-write-honesty-unit1-bb47`, not main.
- R0: it waits for #1604 (the null-block fix, `d3cd254c`) to land on main. #1605 already includes the fix. Until then R0 and everything after it is blocked. Steps 1, 2, 3, 5, 7 proceed.
- Thread 4534140517 (resolver_scheduler.py:1156): stays open until #1604 lands.
- Null-block fix for `prediction_resolver_scheduler` (in #1606 at 0a7635d5, `if block is None` instead of `setdefault`): absent from every split head. Only #1604 changes `internal/council/resolver_scheduler.py` among #1599 to #1605 (its test file `tests/test_resolver_scheduler.py` too). #1605 inherits that file from #1604. Port target checked (2026-11-24): the #1606 patch for that file applies cleanly to #1604's pre-port head `36a7ab30`. The fix is ported into #1604, head `d3cd254c` (test commit `35add609`, fix commit `d3cd254c`, pushed 2026-11-24). The port adds falsy-block cases (`[]`, `0`, `""`, `False`) that #1606 lacks. The file `tests/test_1578_null_scheduler_block.py` has 14 tests. Before the fix, 4 fail (the regression tests) and 10 pass (guard tests that pass on both trees). After the fix, all 14 pass. #1605 includes the fix via merge `71313175`, pushed as a fast-forward. The port's one behavior change (`36a7ab30` to `d3cd254c`) is that a missing key with a declined summary moves from APPLIED to DECLINED. The #1604 body states it. Callers traced (`d3cd254c`): `_cycle_ok` accepts `declined`; `replay.py:156` passes the value through; `pump_lead_recover.py:527` reports its own writer's outcome, not the summary. A repo-wide `persist_outcome` grep outside tests at `d3cd254c`, including JS, HTML, and templates, finds no consumer outside the scheduler's own tick that branches on the value (`resolver_scheduler.py:954` does, for backoff); `PersistResult.committed` has no callers in `internal/council`. Measured 2026-11-24 by calling `_persist_cycle_summary` directly with a newer generation and reading back `last_cycle` and `cycle_history`. The probe was session-local and is not committed. Owner path (`force=False`, `_persist_owner_gen` set): two cycles give APPLIED on `36a7ab30` (pre-port #1604 head) and `d3cd254c`, and `committed=True` on `2a199aec` (main). Force path (`force=True`, the timeout orphan write at `internal/council/resolver_scheduler.py:1323`): a stored timeout row (`complete: False`) followed by an incoming `ok: True` summary leaves `last_cycle` unchanged and adds no history row. The result is DECLINED on `36a7ab30` and `d3cd254c`, and `committed=True` on main. An incoming `ok: False, complete: True` summary behaves the same way. The other 7 of the 9 stored/incoming combinations store the same state in all three trees. The force caller always sends `ok: False`, so the `ok: True` row cannot come from it. Line numbers in this paragraph are at `d3cd254c`. The `ok: False, complete: True` row needs `mark_complete()` to run after the abandon check at `resolver_scheduler.py:1568-1571` and before the snapshot. I have not shown that window. The DECLINED label first appears in `e7b7de70` (#1578 7/8), which is inside #1604's own range (`1b228f0e..36a7ab30`), not in the null-block port commits. So #1604 changes the force-path report from `committed=True` to DECLINED. The timeout caller at `resolver_scheduler.py:1323` discards that return value. The timeout `result` that `_run_refresh_cycle_with_timeout` returns to `:919` is a fresh dict built at `:1305`, and nothing writes `persist_outcome` into it. The worker's own dict gets the label at `:1582` through `_apply_persist_honesty` (`:1917`), and that dict is a separate object the timeout path never returns. So the outer loop's `persist_outcome` read at `:941` finds no label on the timeout result, and no caller can observe the force-path label. The earlier claim that `:941` reads only `ok` was wrong, and this sentence replaces it. Verdict UNDETERMINED: the drop is pre-existing on main, and no test asserts that the write must land. An earlier DECLINED on a fresh install came from a hand-built payload with no `gap_timing_ms`, which production never emits. A completed-success payload gives APPLIED.
- Parked weights fix (thread 4534140530, weights.py emit-failure logging): no split PR among #1599 to #1605 touches `internal/council/weights.py` or `data_seeds/score_snapshots.json`. It has no split owner. The change exists only as a staged index on the local, unpushed branch `claude/fix-1578-weight-emit-log` (803cb9db), in an ephemeral session worktree. It logs a warning when `emit_weight_change` fails, then returns the value, with a 27-line test. It is not on any remote, and no patch file was saved, so it needs re-creating from the branch before any further work. Its seed needs rebuilding from repo-local inputs for `data_seeds/score_snapshots.json`; if that needs production data it stays parked. No hand edit of the digest.
- D2 test: blocked on #1603.

## F. Risks and cheapest checks

- Fault PRs conflict with stack PRs in server.py. Check: `gh api repos/cryptoreporthub/subnet-dashboard/pulls/<n>/files --jq '.[].filename' | grep -x server.py` for each of #1599-#1605.
- state_vector.py timestamp is stored and read back. Check: `grep -rn "timestamp" internal/council | grep -i parse`, and run the council tests, before changing the format.
- A baseline-only gate hides existing bugs. Check: baseline file lists counts per class; review when they drop.
- Scorer touch needs `data_seeds/score_snapshots.json` in the same commit (CLAUDE.md). F2 touches state_vector.py: run `check_invariants.py --check`.
- Counts drift again. Rerun the sweep at each merge; main is authoritative.

## G. Out of scope

Merging or retargeting #1606; the weights.py fix and seed restamp; postmortems.py:56; hand edits of any digest; closing thread 4534140517; the server.py refactor R0 through R12 (planned, not started); the three candidate sweeps (silent except, JSON atomicity, data paths) beyond the baseline.

## H. Summary

This phase lands the stack that is ready, fixes the six faults that are plainly wrong, and puts a gate in place so no new ones arrive while the rest waits its turn.

## I. Review follow-ups (2026-11-24, not yet fixed)

- **Skip row replaces a completed success (pre-existing, B/C).** A `heavy_job_busy` skip at `internal/council/resolver_scheduler.py:858-866` (origin/main) calls `_persist_cycle_summary` without `owner_gen` or `force`. With no timing context, the write takes the `not owned_cycle` branch, which runs before the "last_cycle holds completed successes only" rule, so a completed success in `last_cycle` is overwritten by the skip row. That branch dates from `54b3d891` (#1571), already on main. It does not block #1604. It needs its own fix.
- **#1591 is not test-only.** Its diff includes `internal/council/pump_overlay.py:34`, which adds `st_ino` to the memo key. Its body says 3 files; the diff has 6. The `check_invariants.py --check` gate cannot run at `dfcad050`, because that tree predates `scripts/check_invariants.py` (added on this branch in `b3a34319`). Landing stays held on the owner's GO and an update-branch.
- **Receipts journal grows without bound.** Ditto nit on #1604. Not triaged.
- **#1605 path filter leaks (A, blocks #1605 merge-ready).** The filter in `.github/workflows/unit1-slice.yml` is new in #1605 (commits `85ed78fc`..`f6254f49`, not on main). It omits files the 62 gated tests load at runtime, for example `internal/file_utils.py` (43 gated tests reach it through `predictions_store.py` and `soul_map_io.py`, a static-closure count and an upper bound like the 206 below) and `tests/conftest.py` (loaded for every gated test). A static import closure of the gated tests, with `server.py` excluded, reaches 206 uncovered Python files. That count is an upper bound: `TYPE_CHECKING` and `try/except ImportError` edges are included. A hand-listed filter cannot track that closure.
- **#1605 pushed to 1205412e.** Head `split/1578-pr8` moved from `71313175` to `1205412e9b4b8b42034640679bbf57daf594b3a2`. It was a fast-forward, with no force push.
- **Trigger-rule proof is pending.** The new rule (`paths-ignore` for `docs/**` and `**/*.md`) gets its first real proof only when the stack merges to main, because the workflow runs only on base main. Until then a simulator checked the trigger behavior, not a live run.
- **CI read for 1205412e.** GitHub Actions runs: `total_count` 0. Check-runs: CodeRabbit completed/skipped, and Cursor Automation: Auto-Review completed/neutral. `unit1-slice` did not run, so the sync test did not run in CI on this SHA.
- **Review sources for 1205412e.** The Ditto local review returned PASS, but it worked from a summarized diff, so it is not a full-diff review. A fresh pstack review with 12 lenses and an attack-the-premise pass returned PASS-with-nits and no blocking findings. The Ditto and pstack verdicts are carried from an earlier run (source not recorded). The pstack review covered commit `1205412e`.
- **Nits recorded as follow-ups, not fixed.**
  1. The sync test pins the substring `paths:`, so `paths :` and `"paths":` slip through. Parse the YAML in the test to close it.
  2. Nothing pins `branches: [main]` on push.
  3. The commit trailer names the model, and the attribution reminder names the same. Dismissed, and the pushed history is not rewritten.
  4. If `unit1-slice` becomes a required check, docs-only PRs leave it pending. The old filter behaved the same. Branch protection was not checked.
- **#1605 title is stale.** It still says "path-filtered". Not edited.

## J. D.5 claims, verified by run (2026-11-24, base origin/main 2a199aec)

Runs used a detached worktree at origin/main, removed after. Each claim was run, not only read. The scripts are in the session scratchpad, not committed: `f1a*.py` (F1-A and F2-A) and `f1b_*.py` (F1-B), with output in `run1/`. Each run stubs only the slow callee, and each number below is the one that run printed.

- **F1-A, timeout waits past its budget: proven at 3 sites.** The `.result(timeout=...)` call sits inside a `with ThreadPoolExecutor` block at `server.py:837-839` (8.0s), `internal/simivision/chat_service.py:135-137` (8s) and `internal/learning/dashboard_context.py:120-122` (2.0s). Exiting the block calls `shutdown(wait=True)`, so the caller waits for the callee. Measured: chat_service with a 1s budget returned at 5.0s; dashboard_context with a 2s budget returned at 6.02s; server with an 8s budget returned at 11.4s. Not verified: real production callee durations, and whether these paths run on a request thread.
- **F2-A, aware-datetime "Z" suffix: proven for `server.py:2802`.** `datetime.now(timezone.utc).isoformat()+"Z"` yields `...+00:00Z`, which `fromisoformat` rejects. The reader is `internal/simivision/weighing_room.py:423` (not `internal/council/`, which does not exist). It replaces "Z" with "+00:00", so a value with both suffixes gives "updated recently" where a valid value gives "updated 5m ago". The value reaches `templates/partials/premium/simivision_picks.html:9`. The other two sites (`server.py:2405`, `internal/council/state_vector.py:1313`) show only cosmetic output in the readers found; state_vector has no parsing reader found. Unproven beyond that.
- **F1-B, background work outlives its caller: split.**
  - Telegram backfill: proven. `message_intel/telegram_listener.py:715` (not `internal/message_intel/`) is `fut.result(timeout=180)`. The caller returned False at 180s; the coroutine still wrote its marker at 183s, so a timeout does not cancel the work. The write was a stub; the real `_backfill_gap` write window is not verified.
  - pick_scheduler lost update: refuted. The orphaned worker does reach `_save`, but `internal/council/daily_pick_engine.py:96-139` reloads under a lock and rejects the stale row, so the later write does not win. Not verified: a tie on timestamp granularity.
  - resolver_scheduler auto-retrain: unproven, read-only claim. `maybe_trigger_auto_retrain` (`internal/calibration/scheduler.py:56`) calls `start_retrain_async` (`:100`) with no abandon check. No resolver cycle was run.
- **F2-A ready-local.** Commit `9fffc15ce2f0fceb6613b5b1a464655166e60097` is on local branch `fix/f2a-main-rebuild`, one commit on origin/main. It touches `server.py` (one line, which drops the `+ "Z"` from `updated_at` in `_safe_simivision_payload`) and `tests/test_weighing_room.py` (+21 lines, test `test_weighing_board_updated_ago_reads_producer_timestamp`). Red on main, the assertion diff is `- updated 5m ago` / `+ updated recently` (carried from an earlier run, source not recorded). Green, weighing_room 17 passed, and the endpoint contract 149 passed with 1 warning (both counts carried from an earlier run, source not recorded).
- **Superseded.** `fix/f2a-aware-datetime-z` at `d57fbedd` was built on the docs branch. Do not use it.
- **Invariant gate, differential run.** The CLAUDE.md "0 new" gate cannot run as written on origin/main, because `scripts/check_invariants.py` and `scripts/invariants_baseline.json` are absent there. Run on origin/main and on `9fffc15c` with the same baseline copy, both print 38 hits, 36 accepted, 2 new (counts carried from an earlier run, source not recorded). The new set is identical: `internal/council/resolver_scheduler.py:290` and `internal/judges/postmortems.py:45`. The fix adds zero hits. Neither file has a baseline entry, because the baseline predates the `d3bde0de` refactor.
- **Caller sweep for `updated_at`.** `internal/simivision/weighing_room.py:423-428` parses it after the replace. `server.py:2799-2832` passes it through. `internal/learning/dashboard_context.py:248` copies it without parsing. The template and JS readers use `updated_ago` only. No reader depends on the trailing Z. Persisted data has no weighing meta `updated_at` under `data/` (not verified; `data/` was not read), so the only effect of the old form is the label "updated recently" until the cache regenerates.
- **Pre-push review of 9fffc15c.** PASS (pstack review with the pstack lenses, report only; carried from an earlier run, source not recorded). A Ditto local review was requested for `9fffc15c`. The send timed out with the outcome unknown, so it is not counted as a reply. The pstack review stands as the gate.
- **Ditto outcome for F2-A.** The F2-A review request was sent at `9fffc15c`. Its first send timed out at 60s with an unknown outcome, and it was resent with a client_message_id. The reply arrived as message `39e0c76e`, status completed: PASS with no A-class findings. Its cited line numbers were wrong. It named `server.py:2807` and `weighing_room.py:432`, and git shows `server.py:2802` and `internal/simivision/weighing_room.py:427` (checked on origin/main with grep). Its claim that the new test fails on main rests on the test being absent there, not on an executed run, so treat it as unverified.
- **Follow-ups for F2-A.** `server.py:2405` has the same `+ "Z"` pattern for the learning-trail time. It has a different reader and is not fixed. `internal/council/state_vector.py:1313` is a scorer file, and a fix there requires restaging `data_seeds/score_snapshots.json`.
- **F1-A status.** The timeout bound is still in progress. Do not record it as done.

Open after this section: the telegram write window with the real `_backfill_gap`, the resolver run, and the state_vector consumer.
