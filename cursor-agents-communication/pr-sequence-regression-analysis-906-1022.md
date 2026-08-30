# PR-sequence regression analysis: #906 → #1022

**Status:** STANDALONE companion to `pick-handler-occupancy-scope.md` (PR #1137). Not a subsection of the scope plan — a distinct finding with a distinct deliverable. Plan-edit only. No code. No deploy.
**Date:** 2026-08-30 · **Author:** Ditto, consolidating Replit audit #2 + Ditto .patch spot-check + live PR-body verification
**To:** Cursor (fold into PR #1137 plan doc as a named companion; keep the plan doc itself as the gate surface)

---

## 1. Why this exists as its own document

Every prior pass (mine, Cursor's, earlier reconstructions) treated the abandon-on-timeout/orphan-write behavior as an *emergent property of otherwise-reasonable code* — something to contain going forward. This analysis shows it is the product of a **regression across a specific PR sequence**: a protection that existed, was working, and was traded away for a bookkeeping mechanism that does not do the same job. That is a materially different finding, and it changes the shape of the fix — so it gets its own document.

## 2. The composed lifecycle (PR-cited)

| PR | Date | What it did | Evidence level |
|---|---|---|---|
| **#500** | 07-26 | Daily scoring became a traffic-independent essential workload | audit |
| **#781/#782** | 08-03 | Already documented the tick "wedges the shared Fly VM" | audit |
| **#906** | 08-13 | **The protection that existed.** Added the live-worker overlap guard (`_work_thread.is_alive()`), gated optional schedulers off the essential worker, added regression tests. PR body on root cause: *"abandoned executor/thread work accumulated and competed with the worker's only HTTP process, causing Fly's port 8081 health checks to time out. Web then surfaced the symptom as 'Worker volume temporarily unavailable'."* | PR body verified 2026-08-30 |
| **#1008** | 08-20 | **The removal.** PR body verbatim: *"Fixes the orphaned-worker bug in pick_scheduler.py where a 90s timeout left get_or_create_today_pick running in the background and blocked all subsequent ticks via `_work_thread.is_alive()`."* Replaced the guard with `ThreadPoolExecutor` + `fut.result(timeout=…)` + `shutdown(wait=False, cancel_futures=True)` + generation-token abandonment: *"bump `_work_generation` so late zombie results are discarded; next tick always starts fresh work (no skip-forever path)."* | PR body verified 2026-08-30 (exact diff among its 7 commits still to read at impl time) |
| **#1009** | 08-21 | Forced 15-min retry after timeout regardless of abandoned worker's writes | audit; verify PR body at impl time |
| **#1021** | 08-22 | Nested 4-worker scoring executor, non-cancellable. Own PR description cites ~20 subnets, **1712s wall, 128 CPU-s** vs the 90s budget — implementers' own numbers showing the budget was structurally undersized from the day parallelization shipped | audit quote; verify PR body at impl time |
| **#1022** | 08-22 | Single global `_tmc_refresh_lock`, no acquisition deadline, serializing two different endpoint types behind one lock; docstring: *"peers block on the lock"*; prewarm installed before scoring workers. Diff-verified 2026-08-30 | **diff-verified** |
| **#1025** | 08-23 | File-locked score cache (`fcntl`) — probably secondary candidate, not primary | hedged |
| **#1095/#1128** | 08-28/29 | LivenessTracker migration + DateTrigger re-arm — makes the heavy tick run *reliably*, which exposes the workload lifecycle rather than fixing it | verified |

**The conflict, stated:** "We intentionally removed the only code that knew whether the previous daily worker was still alive, while preserving automatic retries and adding nested, non-cancellable parallel work behind a shared global lock." (Replit audit #2 — primary investigation target.)

## 3. Intentional tradeoff or unintentional regression? — RESOLVED

**The #1008 PR body names `_work_thread.is_alive()` explicitly and presents its removal as the fix.** So:

- **Deliberate replacement, not an oversight.** #906's guard had a real defect: once a worker timed out, the `is_alive` check made every subsequent tick skip forever (permanent wedge). #1008 was written to fix that.
- **Incomplete model of the replacement.** Generation tokens bound *result propagation* ("late zombie results are discarded"). They do **not** bound worker lifetime or side effects: the abandoned worker can still write `daily_picks.json` / HOLD records, hold the `fcntl` lock, occupy the nested scoring pool, and block on `_tmc_refresh_lock`. The token was believed to fully solve the orphan problem; it solved half.
- **Consequence for the fix framing:**
  - NOT "restore what #906 had" — that reintroduces the skip-forever wedge #1008 was fixing.
  - NOT "design something new blindly" — #1008 was trying to achieve a good outcome (next tick always starts fresh).
  - **"#1008's stated goal, completed correctly":** next tick always starts fresh **AND** the previous worker is bounded — join-with-deadline, cooperative cancellation, or true single-flight (no new generation starts while one is alive). Rank 1/2/3/(e) should be read through this lens.

## 4. Sharpened capture checks (§6 item 4 replacement — falsifiable)

Primary capture objective (replaces the open-ended A–E table as primary; A–E remains the fallback interpretation grid if these are ambiguous):

1. **Does a daily-pick-work generation SURVIVE the 90s timeout?** (thread stacks at timeout+5s and +60s via py-spy/faulthandler)
2. **Does the 15-min retry create ANOTHER generation?** (second executor, second nested scoring pool — /jobs + thread inventory at 00:15–00:17Z)
3. **Where are surviving dpick-score threads blocked?** `_tmc_refresh_lock` / network reads / scoring code-GIL / score-cache `fcntl` lock
4. **Does thread count return to baseline BEFORE the retry?**

Deliverable: capture artifact naming the exhausted resource (TMC lock convoy / threads / GIL / network / volume). Runtime capture runs on the affected generation, or the next recurrence, before any impl PR ships.

## 5. Widened gate

The §4 gate ("ranks 2/3/(e) wait on §6 item 4") must be **widened to also require the composed-lifecycle review** — because the two answer different questions:

- **Runtime capture** proves *what* is exhausted.
- **This PR-sequence review** establishes *whether the fix is restoring known-good behavior or building new behavior* into a system that already had it once and removed it deliberately-but-incompletely.

**Gate:** no impl PR ships until BOTH (a) item 4 capture answers "which shared resource" AND (b) PRs #906/#1008/#1009/#1021/#1022 are reviewed as ONE composed lifecycle. Until then, **rank 1 is the only mergeable cut**, with the scope plan's §6 items 1–2 passing.

## 6. What this changes in the scope plan (v4 deltas for PR #1137)

1. **b3 (root latency non-goal):** replace "composed self-conflict" with the resolved framing — *intentional replacement (fixing #906's skip-forever wedge) with an incomplete model: tokens bound results, not worker side effects. Root cause of tonight's signature is the #906 failure mode re-opened by #1008, convoy-multiplied by #1021/#1022.*
2. **Rank framing note:** implement "as #1008's goal, completed correctly" (fresh-start AND bounded previous worker), not "restore #906".
3. **Patch F (composed-lifecycle review):** upgrade the #1008 note — mapping now **PR-body-confirmed** (own description + named tests); exact diff among 7 commits still to read against git history at impl time. #906 diff direction confirmed; #1021 numbers to re-verify against PR body.
4. **Patch D §6 item 4:** replace open-ended capture with the four falsifiable checks above; A–E demoted to fallback interpretation grid.
5. **Widened gate text:** see §5.

## 7. Verification status

| Claim | Level |
|---|---|
| #906 added `_work_thread.is_alive()` overlap guard; fixed abandoned-work-starves-worker-HTTP | PR body verified (root-cause section) |
| #1008 removed the guard, added executor + generation tokens; named the guard as the bug | PR body verified (own description + named tests) |
| #1022 single global TMC lock, peers block, serializes both endpoints | **diff-verified** 2026-08-30 |
| #1128 `if reschedule and still_scheduled:` → `if still_scheduled:` | **diff-verified** 2026-08-30 |
| #1009 forced-retry semantics | audit; verify PR body at impl time |
| #1021 1712s/128 CPU-s vs 90s | audit quote from PR description; re-verify at impl time |
| #1008 exact diff (which of 7 commits) | OPEN — git history at impl time |

---

END. Fold this into PR #1137 as a named companion document; keep the scope plan as the gate surface. No code, no deploy.