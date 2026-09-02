# ROOT-CAUSE SWEEP FINDINGS — cryptoreporthub/subnet-dashboard

Sweep date: 2026-09-02 · HEAD audited: `4fe565e1` (main, 2026-09-02) · Method: full-history pickaxe (`git log -S`), commit/PR diff reads, `gh api` issue/PR reads. READ-ONLY analysis; no code changes made.

Symptom vocabulary matched against (from tasking): busy-handler strings; `/api/daily-pick` ~90s timeouts → pick=null HOLD; resolver silence/read-path silence; ~15s endpoint timeouts + HTTP 422/403 escalation; watchdog backlog; starvation episodes; HOLD persisting past recovery.

---

## STEP 1 — Removed/weakened protections (full-history pickaxe + diff reads)

Legend: **[REMOVED]** protection deleted outright · **[WEAKENED]** guard replaced by a weaker mechanism · **[REPAIRED]** later restored on main (window still matters for deployed prod).

| # | Date | Commit / PR | What was removed/weakened | Classification |
|---|------|-------------|---------------------------|----------------|
| R1 | 2026-08-20 | `1eb0a6bf` (PR #1008) | `_work_thread.is_alive()` skip guard in `internal/council/pick_scheduler.py` (added by PR #906, `fe002bb0`, 2026-08-15) replaced by ThreadPoolExecutor + `_work_generation` token. **Key nuance:** the generation check gates only the RETURN value (`pick_scheduler.py:288-289`); the abandoned worker still executes the full `get_or_create_today_pick` including internal disk writes. | **[WEAKENED]** — illusory timeout |
| R2 | 2026-08-22 | `9009136d` (PR #1009) | DateTrigger retry semantics silently dropped to APScheduler default `misfire_grace_time=1s` (retry missed if scheduler busy); patched to 60s. Also moved subnet load inside the 90s executor (was 278s wall). | **[WEAKENED→re-patched]** |
| R3 | 2026-08-2x | `54805bb5` | misfire_grace 60s default for interval + one-shot jobs. Landed on main **without a PR** (`commits/{sha}/pulls` = `[]`) although PR #1019 exists CLOSED-unmerged — process anomaly. | **[CHANGED, unreviewed path]** |
| R4 | 2026-08-29 | `2e5b27ab` (shipped via deploy vehicle #1131, `73557508`) | misfire_grace 60s→180s after prod v2104 `EVENT_JOB_MISSED` (job 1.35s late with grace=1 while daily pick held the executor 90s; job never re-armed). | **[CHANGED]** |
| R5 | 2026-08-30 | `4e27bead` (PR #1138) | Revert of `a563eeac`/`5c23c59a` "contain 90s tick abandon (ranks 2, 3, e)": deletes `commit_ok` abandoned-worker write gate, deletes `tests/test_occupancy_cuts.py` (114 lines, whole file), un-moves subnet+market load back outside the 90s pool. Revert PR #1138 body discusses only rank-1 GET single-flight; no discussion of ranks 2/3/(e) in the revert PR itself. | **[REMOVED]** incl. a CI test gate |
| R6 | 2026-08-28 | `98677e74` (PR #1090) | `_last_resolver_tick` deleted from `internal/learning/loop_health.py` and renamed `_resolver_liveness_view`; 3 importers never updated (`internal/loop_stall_guard.py:87`, `internal/learning/routes.py:1288`, `internal/council/resolver_scheduler.py:737`) → ImportError dead path; resolver revive never fires. | **[REMOVED]** with broken callers |
| R7 | 2026-08-02 | `4975d684` (PR #762) | Mindmap-summary background single-flight (`_MINDMAP_SUMMARY_REFRESHING` + refresh thread) removed as GIL-starvation stop-bleed; replaced with inline TTL-miss build. Two single-flight tests replaced by inline tests. | **[REMOVED]** (deliberate, documented) |
| R8 | 2026-08-13 | `cc4a28aa` | Outcome watchdog "old loop did not stop; refusing replacement" guard removed; replaced by join-timeout + `_recovery_thread_alive()` re-check logic. | **[WEAKENED]** (replacement logic present) |
| R9 | 2026-08-27 | `8dde3468` (PR #1058) | g0-baseline probe dumps dropped from hydrate PR (probe-dump cleanup, not a runtime guard). | **[REMOVED]** (diagnostic only) |
| R10 | 2026-08-23 | `69b384a1` (#1033) | `ci-verbose.yml` workflow deleted (D1 remediation per H10). | **[REMOVED]** (diagnostic CI) |

Pickaxe sweeps that came back EMPTY (negative evidence): no removals of `Semaphore`, `acquire(blocking=False)`, `max_instances`, `coalesce`, `EVENT_JOB_MISSED` handlers, `os._exit` watchdog, or liveness/stall-guard wiring beyond R6 (which was repaired). `f853fedf` (2026-07-28) ADDED rate limits (strict_limit on scan/trigger POST) — an addition, not a removal; the `2c0a4d85` hit was a docs table mentioning TaoStats 5-calls/min rate limiting, not a code removal.

---

## STEP 2 — Ranked root-cause candidates with citations and symptom match

### Rank 1 — Illusory timeout: abandoned daily-pick worker keeps writing (R1 + R5)
- **Original problem:** PR #906 (`fe002bb0`, 2026-08-15) added the `is_alive()` skip guard because a timed-out tick left a thread still running, so the next tick would double-fire work. PR #1008 (`1eb0a6bf`, 2026-08-20) replaced it with a generation token — but the token only gates the return value, not the abandoned worker's side effects (`pick_scheduler.py:288-289`; full work incl. disk writes still runs).
- **Why weakened:** #1008 was a redesign, not a verified-equivalent swap; issue #1113 (OPEN) documents the Python 3.12 non-daemon pool worker consequence: `score_snapshots.py:307-322` `write_timeout_480s` without cancel, deferred callback at `:498-518`, same motif at `resolver_scheduler.py:433-499`; Sentry shows `cycle_timeout_90s/180s` durations ~40s over budget; `run_at` frozen after late persist.
- **Aggravator:** PR #1138's revert `4e27bead` (2026-08-30) deleted the `commit_ok` abandoned-write gate and `tests/test_occupancy_cuts.py` that pinned this behavior — regression by omission (no contemporaneous discussion of ranks 2/3/(e) in the revert PR body; it discusses rank-1 GET single-flight only).
- **Symptom match: STRONG.** Matches `/api/daily-pick` ~90s timeouts → pick=null HOLD; HOLD persisting past recovery (abandoned worker re-writes HOLD after recovery); busy-handler strings under retry storm (mission-control capture `2f480615`: "00:15Z 90s tick → HOLD 00:17Z … `daily-pick-work` abandoned (`shutdown(wait=False)`), worker may still score/write").

### Rank 2 — start()-vs-persisted-lifecycle wedge: schedulers never armed after restart (issues #1127/#1128)
- **Mechanism:** persisted `lifecycle=started` makes `start()` return "already running" without scheduling jobs → new process generation never arms DateTriggers → `/jobs` missing daily/hour-pick entries while `/health` paints ok (#1128). Score-snapshot deferred-completion persisted ok but didn't re-arm (#1127). Registry truth is `/jobs`, not `/health`.
- **Fix attempt on main:** `a0999992` (PR #1128 arm-on-start, 2026-09-01) — merged; deployment status unverified from this sweep.
- **Symptom match: STRONG** for resolver silence/read-path silence and HOLD persisting past recovery (a wedged scheduler explains why HOLD outlives the incident).

### Rank 3 — Dead resolver revive path (R6, #1112) — repaired on main, window live in prod
- **Mechanism:** `98677e74` (PR #1090, 2026-08-28) deleted `_last_resolver_tick` without updating 3 importers → permanent ImportError inside `_resolver_tick_age_seconds` → stall-guard probe always fails → `revive_prediction_resolver_scheduler` never fires. Verified live defect at HEAD-of-window; repaired by PR #1151 (`44fd2fb7`, 2026-09-01, compat shim + loud probe failures) — **merged but not confirmed deployed**; prior context reports #1151 merged-but-not-deployed.
- **Symptom match: STRONG** for resolver going silent/read-path silence and watchdog backlog (the watchdog that should have caught it was the dead path itself).

### Rank 4 — misfire-grace churn 1s→60s→180s (R2/R3/R4)
- Chain: `9009136d` (2026-08-22, #1009) → `54805bb5` (no-PR landing; #1019 closed unmerged) → `2e5b27ab` (2026-08-29, shipped via #1131). Each bump was reactive to the last missed-fire episode; none re-verified the original failure was gone. The 180s grace can absorb a missed cycle silently — the confirmed "misfire-grace-absorbs-backlog" pattern (mission-control `2f480615`: "misfire_grace_time catch-up remains inconclusive").
- **Symptom match: MODERATE** — explains missed/late cycles and silent absorption, not the 90s HOLD itself.

### Rank 5 — Hydration burst occupancy (#1058 chain)
- `e5575857`/`64176d16` (2026-08-26, #1058) offloaded hydrate handlers to REQUEST_EXECUTOR after a ~25-fetch hydration burst produced live "pick handler busy — retry shortly" HOLD and `/health` 15s timeout + liveness 503 (capture `2f480615`: G0-2). Closed with live proof 3/3 critpath ≤10s (median 3.299s). Partially fixed: rank-1 GET single-flight merged via #1138, but ranks 2/3/(e) reverted (see Rank 1).
- **Symptom match: MODERATE-STRONG** for ~15s endpoint timeouts + 422/403 escalation and busy-handler strings.

### Rank 6 — pump_desk_snapshot unregistered (#1139, OPEN)
- `PUMP_DESK_SNAPSHOT_*` absent from `/api/liveness` since 2026-08-30 07:30Z; prediction_resolver failing 5×, daily_pick stale last_success 00:39:17Z. Related fixes on main: `c248c820` (#1146), `dcf0cc58` (#1147), `99ae1d2f` (#1148) — all 2026-09-01, deployment unverified.
- **Symptom match: MODERATE** for watchdog backlog / read-path silence.

### Rank 7 — Mindmap single-flight removal (R7, #762)
- Deliberate, documented stop-bleed for GIL starvation (commit body: "no bg GIL refresh … starved the event loop"). Removal was the fix, not the regression; residual risk is unbounded concurrent inline builds, mitigated by TTL cache.
- **Symptom match: LOW-MODERATE** (historical starvation episodes).

### Disprove-the-leading-candidate (Rank 1)
- What would refute it: evidence that abandoned workers' disk writes are harmless (e.g., idempotent atomic writes with no HOLD re-write) — **not found**; #1113 and capture `2f480615` show the opposite (frozen `run_at`, HOLD re-write after abandon).
- Counter-consideration honestly noted: the revert `4e27bead` was part of a controlled occupancy experiment (PR #1138 "M4 PASS… merge AND deploy are one act"), so the removal was *known* at merge time — but the revert PR never re-verified the original abandon problem was gone, and `tests/test_occupancy_cuts.py` remains absent from main HEAD (verified: `ls tests/test_occupancy_cuts.py` → No such file). Classification stands: regression by omission with known-but-unweighed removal.
- Alternative that would displace Rank 1: if prod is running a build that predates `4e27bead` (i.e., containment still active in prod), Rank 2 (lifecycle wedge) becomes the primary. Deployment-state ambiguity between main HEAD and prod builds is the sweep's main epistemic gap (mission-control itself records "reconcile prod e86070b vs main" drift, `4e851ef7`).

---

## STEP 4 — "Fix that fixed the wrong thing" audit

| Incident | Stated symptom | Merged fix | Verdict |
|----------|----------------|------------|---------|
| 90s tick orphan (#906→#1008) | orphan thread double-fire | #1008 generation token gating return only | **Wrong-thing-adjacent:** symptom (double tick) quieted; mechanism (abandoned worker writes) untouched → #1113 |
| v2104 EVENT_JOB_MISSED | job never re-armed | `2e5b27ab` grace 60→180s | **Frequency-reducer, not mechanism fix:** grace absorbs backlog silently; capture `2f480615` marks catch-up "inconclusive" |
| Hydration burst HOLD (#1058) | busy-handler, /health 15s | #1059→#1070→#1071 offload + #1138 rank-1 single-flight | **Correct for GET path**; ranks 2/3/(e) reverted same day (`4e27bead`) — mechanism partially re-opened |
| Resolver silence (#1112) | revive never fires | #1151 shim restore | **Correct fix**, merged 2026-09-01; deployment unverified → window may still be live in prod |
| Scheduler not armed post-restart (#1127/#1128) | /jobs missing entries | `a0999992` arm-on-start | **Correct mechanism fix**; deployment unverified |
| pump snapshot liveness gap (#1139) | tracker absent from /api/liveness | #1146/#1147/#1148 | **Plausibly correct**; deployment unverified |
| GIL starvation (July, #762) | event-loop starvation | #762 inline lite build | **Correct stop-bleed**; single-flight protection removed as side effect (R7) |

Pattern: repeated "symptom-quieting" fixes (generation token, grace bump, revert-for-experiment) that left the underlying write-path/lifecycle mechanism intact, plus a cluster of correct mechanism fixes (2026-09-01) whose deployment state is unverified.

---

## STEP 3 — Config & infra drift

### (a) Timeout / worker / VM / scheduler-interval changes (chronological)

| Date | Commit / PR | Change | Stated reason |
|------|-------------|--------|---------------|
| 2026-07-14 | `321a678d` | VM → 1GB + restart on critical health | OOM/health |
| 2026-07-18 | `56f57ea8` | single-process on 1GB | colocated worker OOMs prod (hotfix) |
| 2026-07-23 | `d32f5384` (#452) | BACKGROUND_ON_WEB=off + kill orphan workers | Fly web stability |
| 2026-08-13 | `561d6979` / `4a601a39` | worker → dedicated CPU | Telegram listener isolation |
| 2026-08-20 | `1eb0a6bf` (#1008) | DAILY_PICK_TICK_TIMEOUT_SECONDS=90 introduced with pool redesign | orphan fix |
| 2026-08-22 | `9009136d` (#1009) | misfire_grace default 1s→60s; subnet load moved inside 90s executor (was 278s wall) | DateTrigger retry dropped by APScheduler default grace |
| 2026-08-22 | `9e98a333` (#1024) | web VM shared-cpu-2x/2gb → **performance-1x/4gb** | "Manual scale … pin fly.toml so next deploy does not revert (workers=6 OOM cliff)" — **emergency sizing, never revisited since** |
| 2026-08-2x | `54805bb5` (no PR; #1019 closed unmerged) | misfire_grace 60s default interval+one-shot | unreviewed path onto main |
| 2026-08-28 | `24488f4e` (#1107) | RESOLVER_CYCLE_TIMEOUT_SECONDS 120→180 | resolver wedge (#1100 abandon-timeout work same day: `70d5c3b0`) |
| 2026-08-29 | `2e5b27ab` (ship #1131) | misfire_grace 60→180s both paths (`job_scheduler.py::_JOB_MISFIRE_GRACE_SECONDS=180`) | v2104 EVENT_JOB_MISSED, 1.35s-late drop |
| 2026-08-30 | `a563eeac`→`4e27bead` (#1138) | containment added then reverted same day; 90s unchanged | occupancy experiment |
| current | HEAD `4fe565e1` | `pick_scheduler.py:35` =90s; `RESOLVER_REFRESH_MINUTES=15` (`resolver_scheduler.py:47`); fly.toml `performance-1x`/`4gb` (`fly.toml:134-135`) | — |

Flagged: the #1008-era VM bump (performance-1x/4gb) and the 180s grace/180s resolver timeout are emergency values tuned during incidents and never revisited (no later commit touches them).

### (b) Schema/persistence-format changes to scheduler/resolver/pick-engine files

- `data/predictions.json` is read by `internal/council/resolver.py:70` (PREDICTIONS_PATH), `internal/conviction_alerts/evaluate.py:139`, `internal/bots/market_desk.py:310`, `internal/council/price_reference.py:18`. The file is absent from the repo working tree (runtime volume artifact; prior context: ~4.2MB, fully re-parsed per resolver cycle — consistent with `resolver.py` full-json load pattern; **hypothesis** for the per-cycle parse cost, not directly measured here).
- Format-touching commits found: `dbdadcd4` (2026-08-08, "Update state and analytical tracking data files"), `eb114684`/`06579633`/`c463dfbf` (2026-08-14, learning scope separation), `bb84de10` (2026-08-26, #1057 weight_updates truthfulness after #1056 literal-zero bug), `dcf6b4ca` (2026-08-26, shadow-row expiry). **No commit was found that changed a field's type/meaning/presence in predictions.json without migration** — the #1056 weight_updates literal-zero incident is the closest call (field semantics silently wrong until #1057).
- HOLD-on-disk retry semantics changed by `4428617b` (2026-08-21, "Fix daily pick retry after timeout when disk already has HOLD") — this is the change that makes a stale HOLD persist past recovery if the abandoned worker wrote it (ties to Rank 1).

### (c) Dependency bumps touching concurrency/async/scheduling/HTTP

- No APScheduler major bump found in the window; the misfire-grace regressions (R2-R4) stem from **APScheduler default behavior** (1s grace) interacting with DateTrigger retries, not a version bump.
- Python 3.12 pool-worker non-daemon behavior is the load-bearing runtime change behind Rank 1's illusory timeout (#1113). No pinned-dependency change was identified as the trigger within this sweep (**hypothesis**: runtime image bump; not verified).

---

## STEP 5 — Correlation timeline (incidents vs protection changes)

| Date | Protection change (Steps 1/3) | Incident / symptom episode |
|------|-------------------------------|---------------------------|
| 2026-07-14→18 | VM 1GB; single-process hotfix | OOM episodes |
| 2026-07-28 | rate limits ADDED (`f853fedf`); worker heartbeat cross-machine (`55a32d30`) | TaoStats 5/min event-loop wedge documented (docs `2c0a4d85`) |
| 2026-08-02 | mindmap single-flight REMOVED (`4975d684`, #762) | GIL starvation stop-bleed |
| 2026-08-13 | outcome watchdog replacement guard weakened (`cc4a28aa`); worker split | — |
| 2026-08-15 | **#906 adds is_alive skip guard** | — |
| 2026-08-20 | **#1008 replaces guard with generation token (R1)** | — |
| 2026-08-21 | HOLD-on-disk retry (`4428617b`); stage timing (`221dcf15`) | daily-pick timeout episodes |
| 2026-08-22 | misfire grace 1s→60s (`9009136d`); VM→perf-1x/4gb (`9e98a333`) | DateTrigger retry drops |
| 2026-08-26 | #1058 hydrate offload | hydration burst HOLD, /health 15s + 503 |
| 2026-08-27 | #1058 critpath proof; probe dumps dropped (`8dde3468`) | — |
| 2026-08-28 | **#1090 deletes `_last_resolver_tick` (R6)**; resolver timeout 120→180 (#1107); LivenessTracker migration (#1087) | #1108 deploy failure, #1110 retry; resolver wedge |
| 2026-08-29 | **misfire grace 60→180 (`2e5b27ab`)** | v2104 EVENT_JOB_MISSED |
| 2026-08-30 | **containment reverted, test file deleted (`4e27bead`, #1138)** | G0 ×2 live failures (00:49Z, 00:54Z): busy strings, /health p95 1245ms→15s timeout; 00:15Z 90s tick → HOLD 00:17Z; #1139 liveness gap begins 07:30Z |
| 2026-08-31→09-01 | repair cluster: #1146/#1147/#1148 (pump), #1151 (shim), #1152 (bound fallback), #1128 arm-on-start | #1112/#1113/#1127/#1128/#1139 open issues |
| 2026-09-02 | HEAD `4fe565e1` | sweep date |

**Cluster observation:** the three protection weakenings most tightly coupled to the recurring symptom family (R1 generation-token nuance 08-20, R6 dead revive path 08-28, R5 containment revert 08-30) each preceded or coincided with symptom episodes within 0-10 days, and the 08-30 revert coincided same-day with the G0 double-failure. The pattern is not "removed weeks before symptoms" — it is "removed/replaced as part of an unrelated redesign or experiment, symptoms re-appearing within days, fix merged but deployment lagging."

---

## SINGLE BEST-SUPPORTED HYPOTHESIS (one paragraph)

**The recurring root pattern is "protection replaced by an appearance-of-equivalent mechanism that does not cover the mechanism's side effects, followed by unweighed removal of the containment fix" — confidence tier: STRONG (not confirmed; deployment-state ambiguity between main and prod prevents confirmation).** The template instance is #906→#1008: the `is_alive()` skip guard was replaced by a generation token that gates only the return value while the abandoned worker continues full work including disk writes (`pick_scheduler.py:288-289`; #1113), and when the 2026-08-30 containment (`a563eeac`) was reverted the same day for the #1138 occupancy experiment, the `commit_ok` write gate and its test file (`tests/test_occupancy_cuts.py`) were deleted with them and never restored (verified absent at HEAD `4fe565e1`) — regression by omission. This single mechanism explains the flagship symptom family: 90s tick timeout → abandoned worker persists HOLD-on-disk (`4428617b` semantics) → pick=null HOLD that persists past recovery and re-arms late. Evidence that would move it to CONFIRMED: (1) a prod py-spy/lock dump at next recurrence showing the abandoned worker holding `daily_picks.json`/`pick_score_cache.json` (the capture `2f480615` explicitly names this as the missing artifact); (2) confirmation that the deployed prod build includes `4e27bead` (post-revert) — if prod instead runs pre-revert code, Rank 2 (lifecycle wedge, #1127/#1128) displaces it; (3) Sentry traces showing `cycle_timeout` overruns paired with HOLD writes after the timeout boundary (#1113 partially provides this).

## CHECKED AND FOUND NOTHING (do not re-walk)

- **No removals** of `Semaphore`, `acquire(blocking=False)`, APScheduler `max_instances`, `coalesce`, `EVENT_JOB_MISSED` listener handlers, `os._exit` watchdog, or scheduler liveness wiring other than R6 (pickaxe over `internal/` + `tests/`, full history).
- **No schema-breaking change** to predictions.json or scheduler state files without migration was found; the closest semantic incident is #1056→#1057 (weight_updates literal zero), fixed 2026-08-26.
- **No dependency bump** (APScheduler/http framework) was found as the trigger for the misfire-grace regressions — they are default-behavior interactions, not upgrade artifacts.
- **R8 (`cc4a28aa`)** was examined and its replacement logic (`_recovery_thread_alive`, join timeout) is present and coherent — not classified as a regression.
- **R9/R10** are diagnostic/probe-dump and temp-CI removals, not runtime protections.
- **Rate limiting** (`f853fedf`) was an addition; the TaoStats 5/min wedge was fixed by removing blocking fallbacks (#710 per docs `2c0a4d85`), not by removing a limit.
- **`a75db5e8`/`55a32d30`** is_alive removals are diagnostic-script and refactor-with-equivalent (`get_worker_peer()` wraps `is_alive` at `worker_peer.py:13-17`) — not protection losses.
