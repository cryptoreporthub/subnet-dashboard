# Learning-stack review batch (2026-10-18)

**Owner:** unconfirmed. **Last updated:** 2026-10-18. **Supersedes:** none. **Inputs:** [STATUS-2026-10-17.md](STATUS-2026-10-17.md), [ARCHITECT-VERDICTS.md](ARCHITECT-VERDICTS.md), [REVIEW-BATCH-stable111.txt](REVIEW-BATCH-stable111.txt).

This is the pre-flight pack for an outside reviewer of the learning stack (council, judges, pump desk, weights). It states what is known, what was measured and when, what is unmeasured, and what needs a decision. It does not contain fixes. No commit, push, merge, or deploy was requested for this pack.

## 1. Scope and snapshot

- **Branch:** `claude/port-cursor-config`, HEAD `1e4ddf70`. It is 29 commits ahead of `origin/main` (`3a65d34a`) and 7 behind it.
- **Verdicts commit:** `803e8370` is an ancestor of HEAD. It is **not** an ancestor of `origin/main`, so the verdicts are not on `main` yet (decision D-03).
- **Paths this branch adds or changes against `origin/main` (29 files, from `git diff --name-only origin/main...HEAD`; this list covers new and modified files alike):** `docs/learning-loop/` and `docs/learning-loop-audit-2026-10-17.md` (docs); `scripts/prototypes/` (walk-forward prototypes, fixtures, helpers); `scripts/claude-session-start.sh` and `scripts/install-pstack.sh`; `.claude/settings.json`, `.claude/skills/verify-subnet-dashboard/SKILL.md`, `.mcp.json`, `CLAUDE.md`; and `cursor-agents-communication/mission-control-log.md`. No app path changed: `server.py`, `internal/`, `message_intel/`, templates, static files, and `tests/` are untouched by this branch.
- **Out of scope:** product fixes for the failing tests, merges, deploys, and PR creation.

## 2. Merge and test state

Counts are carried from earlier full pytest runs whose outputs are in the session scratchpad. This pack re-checked one of them: the ID inventory for `ef234c95` has 181 unique IDs and no duplicates. The other counts were not re-checked and are inherited. "Not measured" means no full-suite run is recorded for that ref.

| Ref | Role | On `origin/main` | Full-suite failures |
|-----|------|------------------|---------------------|
| `e620ee4` | Base named in the verdicts header | yes | not measured |
| `ef234c95` | Main tree (`wt-main`) | yes | **181** (ID inventory; an earlier note said 179, not reproduced) |
| `61d49f3f` | #1442, request path reads the snapshot (merged) | yes | not measured |
| `cd0c7b94` | Base of #1458, stacked on #1443 | yes | not measured |
| `3a65d34a` | Current `origin/main` tip (#1458 merged) | yes | **180** (full run: 3250 passed, 5 skipped; IDs in [REVIEW-BATCH-d07-3a65d34a.txt](REVIEW-BATCH-d07-3a65d34a.txt); log kept in the session scratchpad, not committed) |
| `2c3642d2` | `claude/fix-council-ui-tests` | no | **158** (inherited) |
| `772024ec` | `claude/fix-daily-pick-root-publish` | no | **137** (138 on second run; inherited) |
| `a9ca00d0` | `claude/fix-weight-learning-core` | no | not measured |
| `803e8370` | Verdicts commit | no | n/a (docs only) |
| `1e4ddf70` | Branch HEAD (after `2966ebf3`) | no | n/a (docs only) |

Caveat: the 181 on `main` is for `ef234c95`, not the tip `3a65d34a`, which gives 180 in its full run. Against `ef234c95`, 179 IDs are common. One ID is only on the tip: `tests/test_price_fetcher_concurrency.py::test_unavailable_cache_expires_after_30_seconds`. Two are only on `ef234c95`: `tests/test_phase_g_mindmap_graph.py::test_mindmap_graph_empty_state_success` and `tests/test_price_fetcher_concurrency.py::test_lock_timeout_returns_fetched_candles`. All 111 stable IDs fail on the tip.

## 3. Failure inventory

### 3.1 The 111 stable failures

The 111 test IDs that fail on all three measured full runs (`ef234c95`, `2c3642d2`, `772024ec`) are listed in [REVIEW-BATCH-stable111.txt](REVIEW-BATCH-stable111.txt), one `file::test` per line. The file was checked: 111 lines, no duplicates.

This is an intersection, so a test that passes on any one of the three trees is not in it. `a9ca00d0` was not part of the intersection.

No per-test root cause is recorded for these 111. Only the subsets in 3.2 and 3.3 have a class.

### 3.2 Order-dependent candidates (two, unconfirmed)

Comparing the main-tree inventory (`fail-main-ids.txt`) with the isolation inventory (`fail-iso.txt`) gives one test in each direction. These are the two candidates:

- `tests/test_scenario_memory.py::test_learning_stats_includes_scenario_memory` fails in the main-tree inventory and not in the isolation inventory.
- `tests/test_price_fetcher_concurrency.py::test_unavailable_cache_expires_after_30_seconds` fails in the isolation inventory and not in the main-tree inventory.

The classification notes also say the sets differ by two order-dependent tests, which matches. The notes name `test_degraded_homepage_has_council_weights` as failing only after earlier tests. Both inventories list it, so the files do not support that. The notes' warm/reset helper is marked "to verify" and was not verified. `fail-iso.txt` does not record which tree it ran on, so the isolation side of the comparison is unverified.

The four names in an earlier draft of this section are withdrawn. `test_concurrent_fetches_keep_both_subnet_keys` fails in both inventories, so the files do not show it as order-dependent. The other three names appear in neither inventory and are not in [REVIEW-BATCH-stable111.txt](REVIEW-BATCH-stable111.txt).

**Commit `bb4ce004` (STATUS section 11).** `bb4ce004` is an ancestor of `origin/main`. Across the 40 test files that import `chain_client`, `score_snapshots`, `message_intel.rollup`, or `build_cost`, `49faea95` and `bb4ce004` give identical 10-failure sets (651 passed, 1 skipped each). So `bb4ce004` added no failures in that slice. STATUS section 11 says "3 failures" for the related 341 tests. That is not the same test set, and its three names are not recorded, so the claim is unreconciled. Nine of the ten slice failures are in the tip's full-run list. The tenth, `tests/test_judges.py::test_api_judges_returns_200`, passes when run alone on the tip and is absent from the tip's list. That is an unconfirmed order-dependence observation, not a candidate in the list above.

### 3.3 UI and message-intel slice (22 `FAILED` lines in the scope file)

`scope-failed-main.txt` has 22 `FAILED` lines for this slice. The classification notes give 28 for the same scope. That gap is unresolved, and this section uses the file's 22. The notes list these areas: conviction, daily-pick, message-intel, OHLCV call quality, proof, pump alert, Summers Telegram, and Telegram proof tests. The classification from the notes is:

- **(a) Lost behaviour.** Source: the `3eadeee9` upload removed 726 lines from `council_stage.html`. Some fixes were proposed in the notes (alert button hidden when disabled, stale badge, HOLD reason read from `hold_reason`). Several items were left unfixed in the notes: horizon badge and chips, pump chip, netuid identity band, evidence-empty panel, weight-nudge visual.
- **(b) Stale test markers.** The tests assert old markers. The notes propose rewriting them to check behaviour (gauge states, motion layers, soul orbs to arc cards, and similar).
- **(c) Removed feature with evidence.** Commit `fca4fb94` deliberately replaced the smoke atmosphere and pewter card with clear cosmos glass. The notes propose rewriting the CSS contract tests to the clear-glass design.

The notes record proposals. None of them is applied in this pack.

## 4. Proposals by class (owners unassigned)

| Class | Proposal | Waiver candidate? | Owner |
|-------|----------|-------------------|-------|
| Order-dependent candidates (3.2) | Confirm the two candidates, then fix isolation (shared state; a warm/reset helper was noted but not verified) | no | unassigned |
| 3.3 (a) lost behaviour | Restore the behaviour, then the tests pass | no | unassigned |
| 3.3 (b) stale markers | Rewrite assertions to behaviour, then the tests pass | no, unless a reviewer accepts the rewrite | unassigned |
| 3.3 (c) removed feature | Rewrite CSS contract tests to the clear-glass design citing `fca4fb94` | yes, with that commit as evidence | unassigned |
| Remaining 111 minus the above | No class recorded yet. Triage needed before any waiver | undecided | unassigned |

## 5. Decision register

| ID | Question | Status | Who decides |
|----|----------|--------|-------------|
| D-01 | #1442 merged to `main` at 2026-10-18T00:58:22Z, closed as draft (`draft: true`), and its body says "Do not merge without GO". #1443 merged at 2026-10-18T00:58:20Z, not a draft, and its body says "Do not merge without Joshua GO." The user states that GO was given for both in a Cursor chat. That chat is not visible from this session, so the GO is user-stated and unverified here. Ratify both on that statement, or revert? | open; GO user-stated, unverified in session | user |
| D-02 | #1458 merged while its body says "Draft, not for merge", but the PR was not a draft when merged. Ratify? | open | user |
| D-03 | The branch is 29 commits ahead of `origin/main`, including the verdicts commit `803e8370`. None of those commits are on `origin/main`. Land them on `main`, or keep them on the branch? | open | user |
| D-04 | Which fix branch is canonical for the 111: `claude/fix-council-ui-tests`, `claude/fix-daily-pick-root-publish`, or `claude/fix-weight-learning-core`? | open | user, with owners |
| D-05 | Accept class 3.3 (c) as a waiver, citing `fca4fb94`? | open | reviewer |
| D-06 | Name an owner for each class in section 4. | open | user |
| D-07 | Run the full suite on current `origin/main` `3a65d34a` before review? | run done: 180 failed, 3250 passed, 5 skipped (section 2). Whether that run is the review baseline is open | user |

## 6. Review protocol and exit criteria

**Protocol.** Review at the pinned head SHA and note the base SHA. Run `pytest` and record the output. Post PASS, BLOCK, or MODIFY with the output and an explicit unverified list (`CLAUDE.md`, Review discipline). No merge and no deploy without an explicit request. Test runs write `data/*.json`: do not commit those, and restore them before finishing (`.claude/skills/verify-subnet-dashboard/`).

**Exit criteria.**

1. Every ID in `REVIEW-BATCH-stable111.txt` is either fixed or waived with a named owner and written evidence.
2. The order-dependent tests confirmed in 3.2 pass in the full run on the target head, after the candidate list is confirmed.
3. `tests/test_endpoint_contract.py` passes on the target head (the Fly Deploy Guard runs it).
4. D-01, D-02, and D-03 are answered.
5. The review states which head was tested, and the unverified list is attached.

## 7. Risks and dependencies

- **Order dependence.** Tests share state, and some write `data/*.json`. Results can change with test order, which is why section 3.2 exists.
- **Tree drift.** The branch is 7 commits behind `main`. The counts in section 2 come from different trees, so they are not directly comparable.
- **Evidence limits for learning claims.** The walk-forward and ledger results carry the limits recorded in [STATUS-2026-10-17.md](STATUS-2026-10-17.md): off-policy grading, no multiplicity correction, and shadow rows excluded from estimators.
- **Coordination.** Ditto answered search calls in this session, so it is reachable. The status memory is saved (id `c30fa747-6895-4b69-9e76-f5f10edac858`). The 2026-10-18 entry in `cursor-agents-communication/mission-control-log.md` exists (line 351, commit `03f122d8`). It records #1443 and #1458 merged, #1459 open as a draft, and #1442 not re-checked. The update to board memory `f93f7202` is still pending and waits for the user's confirmation. This is recorded, not treated as a blocker.

## 8. Cross-links

- [STATUS-2026-10-17.md](STATUS-2026-10-17.md): verified state, sections 5, 10, and 11.
- [ARCHITECT-VERDICTS.md](ARCHITECT-VERDICTS.md): architect verdicts, method and limits in section 0.
- [REVIEW-BATCH-stable111.txt](REVIEW-BATCH-stable111.txt): the 111 stable test IDs.
- [REVIEW-BATCH-d07-3a65d34a.txt](REVIEW-BATCH-d07-3a65d34a.txt): the 180 test IDs from the full run on `3a65d34a` (D-07).
- `docs/learning-loop/ROOT-CAUSE-REPORT-2026-10-17.md`: source findings (F1-F51, RC1-RC11, FX1-FX11).
- `docs/learning-loop-audit-2026-10-17.md`: audit source.
- `scripts/prototypes/`: walk-forward prototypes and fixtures.
