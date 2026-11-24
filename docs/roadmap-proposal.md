# Roadmap placement proposal

This page proposes where the bug sweep, the open PRs and issues, and the server.py refactor fit into the roadmap of record. It is for the owner and for the session that keeps the roadmap. Nothing here has been executed.

The roadmap of record is `docs/phase-plan-known-bugs.md` at `254e099c` on branch `claude/trusting-mendel-8eg87v`. It already adopts the register in `docs/bug-sweep.md`. This page adds to it and does not replace it. Facts are from `main` at `2a199ae` on 2026-11-24.

## The short answer

The refactor does not wait for the whole sweep. It waits for three things, and most of the sweep can run beside it.

| Work | Needs first | Conflicts with | When |
|---|---|---|---|
| Fault PRs F1-A (3 timeout sites) and F2-A (timestamps) | nothing | `server.py` hunks differ from #1603 (line 2802 against its hunk near 2733), so a clean merge is likely and untested | now |
| Sweep gate `--fail-on` with a stored baseline | nothing | none | now |
| `degraded()` helper that only swaps the exception text for a fixed code, then the 26 exception-text routes in files no open PR edits | nothing | none. Post on the agent board first, because `internal/analytics/*` belongs to Agent B | now |
| Hermetic test fixture and failing-test triage | nothing | `tests/conftest.py` is loaded by every gated test, so it needs its own PR | before R0 |
| Status-code changes on those routes | a consumer check per route | readers in `static/js` and outside automation | one route at a time, after the helper |
| Stack #1599 to #1605, and #1591 | review | `server.py` (#1603) | as planned |
| R0 to R9 | stack landed, null-block fix (#1604 at `d3cd254c`) on `main`, hermetic fixture | the 49 files the plan names | after the stack |
| Candidate queues in files that neither the stack, the refactor, nor any other open PR edits | nothing | none | beside R0 to R9 |
| Candidate sites in files other open PRs edit (for example `live_subnets.py` and drafts #1473, #1475, #1540) | the owner decides each draft | those drafts | after that decision |
| Candidate sites in files the stack changes | stack landed | the stack | after the stack |
| Candidate sites in files the refactor touches, and 13 exception-text routes | R9 | the refactor | after R9 |
| R10 and R11 | R9, and the fault PRs | none | last |

## How the numbers were made

Each site goes in one of four buckets by its file. "Refactor" means the file is one of the 49 the refactor plan edits or imports from `server`. "Stack" means it is one of the 30 Python files that #1599 to #1606 change. "Other PR" means one of the remaining 55 open PRs edits the file. "Clean" is everything else.

| Class | Total | Clean now | Other open PR | Wait for the stack | Wait for R9 |
|---|---|---|---|---|---|
| Swallowed exceptions | 223 | 89 | 42 | 61 | 31 |
| JSON written straight to its path | 59 | 35 | 12 | 10 | 2 |
| Hardcoded data paths | 133 | 93 | 16 | 11 | 13 |
| Exception text in route replies | 54 | 26 | 0 | 15 | 13 |

The buckets sum to each total. The main "other PR" collisions are `internal/live_subnets.py` (7 swallowed exceptions, 2 JSON writes, drafts #1473, #1475, #1540), `internal/judges/subnet_judges.py` (#1448), `internal/council/ab_benchmark.py` (#1451), `internal/conviction_alerts/evaluate.py` (#1561), and `internal/council/mindmap_bridge.py` (#1578, #1561, #1444).

Three limits apply. The sets are file-level, so a file the refactor edits in one place keeps all its sites in the "wait" columns, which makes "clean" a floor. The stack file list was read in full, after a first read capped at 40 files cut #1604 short at 40 of 44, and the four missing files were not Python source. The sweep matches syntax, so each site is a place to look and not a confirmed bug, except exception-text routes, which a probe confirmed.

## What the register adds to phase 1

- **Unblock exception-text routes.** The phase plan holds them until R10, which means until R0 to R9 and the stack have landed. That leaves a confirmed information leak open for weeks. The root cause is that no route has a boundary handler. Add the `degraded()` helper now at `internal/web/replies.py`, the place the refactor plan already names, so that R10 never moves it. Keep the first PR small. It swaps `str(exc)` for a fixed error code and logs the exception, and it changes no status code. The 26 clean sites sit mostly in `internal/analytics/store_routes.py`, `internal/analytics/routes.py`, `internal/pump_tracker/routes.py`, and `internal/trace/routes.py`, and their readers in `static/js` and in outside automation are unchecked. Change a status code on one route only after its readers are checked. Where a reply carries usable data, the dashboard's fetch helper drops the body of any non-200 status, so those routes stay 200. The 15 sites in `internal/learning/routes.py` come later, because #1600 and #1604 edit that file.
- **Fix the timeout recipe.** `shutdown(wait=False)` stops the caller waiting. It does not stop the worker, and pool workers are non-daemon. The phase plan already notes that the chat site leaks one worker per timed-out message. Add a single-flight guard to that site, and use a daemon thread where an exit-time join can hang CI, as `_warm_homepage_cache` does at `server.py:929`.
- **Make the test fixture its own PR.** The contract test modifies tracked files under `data/`, and issues #1470, #1568, #1518, #1566, #1596, and #1482 are the same isolation problem. The phase plan lists the 160 failing tests as "Not triaged, owner none". Give that row an owner, and let the refactor's R0 fixture be this PR instead of a second one.
- **Check what the fixture cannot redirect.** I found the writers of ten of the twelve files that a test run dirtied. Each builds its path from a relative `data/...` literal or an environment override, so a fixture that sets the working directory to a temporary copy and sets those variables redirects them. Two are different. `data/.worker_heartbeat` goes through `internal/data_volume.py`, and I found no writer in non-test code for `tests/.liveness_allowlist_prev.json`. The fixture PR should end with `git status --short` empty after a full run, which settles both.
- **Close superseded PRs, after F1-A lands.** #1330 duplicates the `dashboard_context.py` fix. #1331 duplicates the `chat_service.py` fix, but also changes `static/js/chat_stream.js`, which F1-A does not touch, so review that half separately. #1186 proposes a freeze that the refactor contradicts. Closing is the owner's call.
- **Keep one sweep script.** The `--fail-on` version is local on `sweep/d1-fail-on`. Push it, and let the copy on `claude/keen-goldberg-ud7grj` defer to it.

## Open issues and PRs the phase plan does not cover

All were open on 2026-11-24. The gate column says what must land first.

| Area | Items | Gate |
|---|---|---|
| Security | The October survey in #1512 still holds on `main`. The Dockerfile has no `USER`, so the container runs as root. `pytest` is unpinned in `requirements.txt`. Writes are open when `WRITE_API_TOKEN` is unset. Even when it is set, four browser write paths stay public by design (`internal/write_auth.py:19-26`), and one of them, `POST /api/mindmap/feedback`, writes to the learning engine (`server.py:2357`). I did not trace whether that changes expert weights. Five workflows triggered by labels reference secrets. Drafts #1444 and #1445 were written to close that public write path and to bound public inputs. | Prod secret state needs `flyctl`, and agent Fly tokens are invalid. #1444 conflicts with the refactor. |
| Resolver and ledger | #1559, #1565, #1569, #1552, #1553, #1517, #1521, #1113, #1596 | The #1578 stack, which changes the same files |
| Designs awaiting owner sign-off | #1508, #1509, #1510 | Owner |
| Volume and memory | #1399 orphaned temp files, #1496 and #1538 production out-of-memory kills | Fix the temp-file reaper before converting any JSON writes to `safe_write_json` |
| Tests | #1470, #1568, #1566, #1518, #1482, #1477 | The hermetic fixture |
| Live subnet data | #1471 with drafts #1473, #1475, #1540, plus #1396, #1376, #1375, #1372, #1395, #1531 | Owner |
| Review gate bot | #1522, #1526 to #1529, #1573 | Separate product, separate owner |
| Learning-loop stack | There are 13 open drafts in #1444 to #1457. The PR body of #1444 describes a 12-branch integrated tree with 146 failing tests against 180 on `main`. Which 12 form the tree, and the counts, are unverified. | Owner decides keep, rebase, or close |
| Pull request hygiene | 63 open PRs, 36 of them drafts, 33 untouched since before November 1, all from one account, with 44 open issues | Owner |
| From the phase plan's own review notes | the skip-row overwrite fix on a local branch, the #1605 path-filter leak that blocks #1605, receipts journal growth, the Telegram cursor redesign, and #1591 now touching 6 files including `pump_overlay.py` | The phase plan's owner |

## Items from memory and Ditto that survived the GitHub check

Ditto's search returned 25 items from August to November, each labelled known or guess from memory. I checked the ones I could against GitHub and the code. Most were already closed or merged.

**Already done, so not added.** The postmortem path traversal (#1367) is fixed on `main` through #1370, which checks the judge registry and the resolved path. Also done are #1058, #1151, #1192, #1210, #1267, #1335, #1344, #1355, #1357, #1358, #1369, #1500, #1506, and #1571. The daily-pick "yesterday's HOLD served as today's" fix is in `api_daily_pick` on `main`. PR #1313 closed unmerged, and the F04 stale-write thread is covered by the open design #1509 and the merged #1598.

**Still real.**
- The workflow directory holds 27 `*.yml` files on `main`. A November 18 memory recorded 22 after a cleanup, with five flagged dead workflows awaiting deletion. Four of the 27 are triggered by labels and reference secrets.
- The browser error-tracking plan in `docs/sentry-browser-sdk-plan.md` was never shipped. No `static/` or `templates/` file on `main` mentions Sentry.
- `read_soul_map(copy_blob=False)` returns the shared cache object. Callers on `main` are `internal/council/memory_scoring.py:31`, `scorer_identity.py:86`, and `weights.py:915` and `:1075`. Ditto's item says the hazard was documented and not changed. I did not check whether any caller mutates the result. That audit is a small, well-bounded job.
- Production out-of-memory kills (#1496, #1538) and the persist-ownership design from November 8 are real and tracked, and the resolver issues in the table above cover the second.

**From the session list, not memory.** Several November 18 sessions were blocked because the Fly token is invalid in agent environments. That also blocks checking the production secret state.

**Needs a GitHub check before anyone acts.** Ditto marked these known or guess, and I did not verify them. Uncached message-intel loads causing web out-of-memory kills with the single-flight fix never landed (memory `4b6c1caa`). Review-gate-bot scrubber missing high-entropy credentials (`c948b552`). RSS growth from `pump_ladder.json` loads with an unexplained 446 MB plateau (`5372bf68`). A test file omitted from the CI list with confirmed defects (`20b7fb0f`), which the CI list sync check in #1605 may already cover.

## Corrections to my earlier material

- The register said 225 swallowed exceptions. `main` has 223.
- I called #1591 test-only. Its head moved, and it now has 6 files including `internal/council/pump_overlay.py`.
- My first timeout recipe recommended `shutdown(wait=False)` alone. See the fix above.

## Not verified

- Whether production sets `WRITE_API_TOKEN`.
- Whether tests pass after F1-A, F2-A, and the stack combine. `git merge-tree` shows F2-A and F1-A each merge into #1605, and into each other, with 0 conflicts. That is a textual check only.
- The 146 against 180 failing-test claim for the learning-loop stack.
- Whether the Telegram "bot is not a member of the channel" errors from the October 5 log triage are still firing.
