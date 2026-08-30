AMENDMENT v4 (CONSOLIDATED — supersedes v3) — fold into pick-handler occupancy scope plan (2026-08-30).
Plan-edit only. No code. No deploy. Do not re-derive; ground-truth edits.
Sources: source-verified review vs cfbe842a; Replit deep-dive commit history (2nd audit);
Ditto symptom-reverse reconstruction; Ditto .patch spot-check (2026-08-30):
#1022 and #1128 diff-verified; #906 directionally confirmed, #1008 mapping UNVERIFIED.

──────────────────────────────────────────────────────────
PATCH A → Section 2, after the Baseline table
──────────────────────────────────────────────────────────
Add:

RECURRENCE, NOT A ONE-OFF — AND A SELF-CREATED COMPOSED CONFLICT:
Daily scoring became a traffic-independent essential workload on 2026-07-26
(PR #500). By 08-03, PR #781/#782 already documented the tick "wedges the
shared Fly VM". Subsequent PRs form one lifecycle, and the conflict spans
their boundaries:

 08-13  #906   overlap protection (worker-liveness guard; executor removed
               from _tick — direction diff-verified, exact guard pending
               review)
 08-20  #1008  "orphan thread" rework — guard replaced by generation counter;
               worker abandoned, not cancelled (DIFF UNVERIFIED — see Patch F)
 08-21  #1009  forced 15-min retry after timeout regardless of abandoned
               worker's writes
 08-22  #1021  nested 4-worker scoring executor, non-cancellable
               (baseline cited: ~20 subnets, 1712s wall, 128 CPU-s — workload
               far exceeds the 90s budget)
 08-22  #1022  global single-flight TMC lock — DIFF-VERIFIED: "peers block on
               the lock"; serializes both TMC endpoints; assumes "refresh
               window is short"
 08-23  #1025  file-locked score cache (fcntl)
 08-28-29 #1095/#1128 liveness migration + DateTrigger re-arm (makes the
               heavy tick run reliably; does NOT fix the workload lifecycle)

THE CONFLICT, STATED: "We intentionally removed the only code that knew
whether the previous daily worker was still alive, while preserving
automatic retries and adding nested, non-cancellable parallel work behind a
shared global lock." (Replit audit #2 — primary investigation target.)

Same-signature recurrences: 08-19 (tick timeout → HOLD, busy handler,
alerts 422), 08-21 (HOLD busy-handler, tick timeout, endpoints OK), 08-25
(HOLD busy/retry, watchdog pending >48h); pump-alerts line degrading since
07-27. 08-29 ~03:00Z: scheduler wedge reverse-engineered (write timeouts
leave tick-active flags set; regression traced to LivenessTracker
migration #1087, merged 08-28 13:04Z). Tonight (00:15/00:17Z) is the
latest instance.

NOTE: 00:39Z directional-conflict HOLD proves the engine CAN finish inside
90s — the timeout is long-tail/ambient, not baseline. Consistent with the
convoy thesis: fast path = early council exit; slow path = full scoring
under TMC/cache contention.

Baseline must state which recurrences the cuts explain (08-19/08-21/08-25
handler-busy HOLDs + tonight) and which they do not (alerts-line
degradation, resolver freshness).

──────────────────────────────────────────────────────────
PATCH B → Section 3, Tick map, after "On FuturesTimeoutError"
──────────────────────────────────────────────────────────

(b1) SIDE-EFFECT WINDOW (critical): the abandoned worker is NOT cancelled
(pool.shutdown(wait=False, cancel_futures=True)). It may still write
data/daily_picks.json and prediction/HOLD records (daily_pick_engine.py:
184-225, 250-284, 286-325) before the generation check
(pick_scheduler._work_generation) rejects its returned payload. Generation
guard stops stale RESULT propagation, not writes.
EPISTEMIC STATUS: independent corroboration across THREE reconstructions —
code-forward (source-verified review vs cfbe842a), symptom-reverse (Ditto
from 00:49 shared starvation), PR-composition (Replit audit #2). Stronger
than any single path. Required in the impl PR's verification as a
post-timeout side-effect audit.

(b2) RANK 2 REVERSES CURRENT DESIGN — CONTAINMENT, NOT ROOT FIX: today,
_load_capped_subnets() and _market_context() run OUTSIDE the 90s future on
the APScheduler thread (verified vs cfbe842a: pick_scheduler 265-297). Rank
2 deliberately moves them inside so abandonment reclaims them and
APScheduler can re-arm (wedge #1087 — grounded). Moving the load inside
does NOT reduce the work — it contains it. Root occupancy reduction comes
from ranks 1 and 3. The impl Go must NOT "preserve" the current outside
placement; the reversal is the fix.

(b3) ROOT LATENCY CAUSE — NAMED NON-GOAL OF THIS PLAN: the underlying cause
is the composed self-conflict in Patch A (guard removal + forced retries +
nested non-cancellable work + global TMC lock). Cuts 1-4 contain the
aftermath; they do not resolve the conflict. This plan measures and bounds;
the composed-lifecycle review (Patch F) and hypothesis-driven capture
(Patch D) confirm the exhausted resource. Follow-up Go (separate) resolves
the conflict at the PR-composition level. If the tail degrades (TMC
latency, subnet-count creep toward cap 24, ambient web-tier contention),
the same episode recurs on a longer cycle even with all cuts shipped —
accepting this Go knowingly.

──────────────────────────────────────────────────────────
PATCH C → Section 4, ranked-cuts table
──────────────────────────────────────────────────────────
Add row + closing note:

| 4 | (e) generation-counter hardening | Pre-persistence check in
get_or_create_today_pick: bail before writing daily_picks.json / HOLD if
_work_generation no longer current. | Low-Med | Touches engine write
path | Post-timeout stale writes (b1) |

Closing: (e) closes the (b1) window. If scope tight, defer (e) to its own
Go with a one-line why — do not silently drop it; it is the only cut
targeting the post-timeout write race.

──────────────────────────────────────────────────────────
PATCH D (REWRITTEN) → Section 6, Validation
──────────────────────────────────────────────────────────
Replace the open-ended runtime-capture item with HYPOTHESIS-DRIVEN capture.
Primary suspect named: global TMC lock convoy (#1022) + generation overlap.

Validation items 4-8:

4. RUNTIME CAPTURE — CONVOY HYPOTHESIS TESTS (from the affected generation,
   or the next recurrence, before any impl PR ships):
   a) Does a daily-pick-work generation SURVIVE the 90s timeout?
   b) Does the 15-min retry create ANOTHER generation (second executor,
      second nested scoring pool)?
   c) Are surviving dpick-score threads blocked in: _tmc_refresh_lock /
      network reads / scoring code-GIL / score-cache fcntl lock?
      — py-spy/faulthandler thread stacks at timeout+5s and +60s
      — /jobs inventory: which jobs registered/fired at 00:15-00:17Z
   d) Does thread count return to baseline BEFORE the retry?
   Deliverable: capture artifact naming the exhausted resource (TMC lock
   convoy / threads / GIL / network / volume). Also verify the
   #1008 orphan-thread diff and #906 guard removal while inside the code
   (Patch F intersection).

5. ISOLATE MISFIRE GRACE: misfire_grace_time=180 (deploy 7355750) can
   ABSORB catch-up backlog rather than fix occupancy. A validation run with
   backlog absorption MUST NOT be credited as occupancy improvement. State
   per run whether catch-up occurred; treat absorbed runs as inconclusive.

6. #1128 CONTRACT SCRUTINY (DIFF-VERIFIED 2026-08-30): `if reschedule and
   still_scheduled:` → `if still_scheduled:` in both Daily and Hour schedulers;
   run_once(reschedule=False) now re-arms when singleton (test
   test_daily_run_once_rearms_when_singleton). Deliberate per commit message
   ("Does not close #1060"). Not Aug-30 root cause without runtime evidence;
   but the weakened run_once contract must be tracked as a separate
   correctness item — an accidental run_once caller can now become a
   repeating scheduler.

7. GATE: no impl PR ships until item 4 answers the exhausted-resource
   question AND Patch F's lifecycle review is complete. Until then rank 1
   is the only mergeable cut, with items 1-2 passing.

──────────────────────────────────────────────────────────
PATCH E → Section 5, Constraints
──────────────────────────────────────────────────────────
Add:

LINE-REF DRIFT IS OPEN, NOT RESOLVED: two sources cite different ranges for
the same regions (pick_scheduler 270-302/317-374 vs 265-297/312-369;
daily_pick 148-221 vs 162-221). Whether these are the same code at
different HEADs is UNVERIFIED. Implementation Go must `git show` against
current HEAD and re-pin ALL line refs before citing either set. No plan
section is authoritative on line numbers until then.

──────────────────────────────────────────────────────────
PATCH F (NEW) → Section 5, Constraints (after Patch E item)
──────────────────────────────────────────────────────────
Add:

COMPOSED-LIFECYCLE REVIEW — PRECONDITION GATE (recommended by Replit audit
#2; agrees with rank-1-first posture): do NOT approve later ranks of this
plan until PRs #906, #1008, #1009, #1021, #1022 are reviewed as ONE
composed lifecycle. The conflict exists across those PR boundaries — the
overlap guard was removed in the same era retries were forced and nested
non-cancellable work + global lock were added. Notes from .patch spot-check
(2026-08-30): #1022 (TMC lock) and #1128 (reschedule contract) are
DIFF-VERIFIED; #906 direction confirmed (executor removed from _tick) but
exact guard unverified; #1008 mapping UNVERIFIED — first visible commits are
tmp-reaper and Stage 2b soak, not the orphan-thread change; the orphan-thread
commit may be later in the PR but must be confirmed against git history
before any plan statement cites it. The review is read-only; no code, no deploy.

END. Re-emit the amended plan in full, newest-first MC log, status
"PLAN SUBMITTED — amendments v4 (final) applied, awaiting Joshua review".