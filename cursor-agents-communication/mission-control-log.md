# Mission Control log (Ditto-readable)

> **Composer** (Cursor Cloud Agent) operates **all six fleet roles** (Mission Control, Sentinel, Drift/QA, Market Desk, Proof Scout, Shield). Bot-directed tasks route here. **Ditto** remains outside reviewer. **Automation-first:** Joshua delegates merge/deploy authority; routine merges + **`fly-deploy` label** deploys are autonomous unless a PR is explicitly gated (#1088-style behavior change) or policy §3.1 requires human approval.

**Snapshot:** Fri 2026-08-28 **7:04 PM MST** (02:04Z Sat) — last read-only round done; **#1113** stands (FP7 undetermined; FP8 revive **OBSERVED** 1:05:53 PM MST / 20:05:53Z); no #1114; freeze 1:18:26 PM MST; strike **64/2**; KILL=0; hold **Sat 11:52:52 AM MST**

**Clock:** operator-facing times = **Arizona MST** (`America/Phoenix`, UTC−7, no DST). UTC kept on Fly/Sentry/git evidence.

---

## Governance

- **#1080 / #1088 → #1100:** Joshua sign-off **ship it** (2026-08-28). Merged #1100 + deployed; #1088 closed superseded.
- **#1107:** `RESOLVER_CYCLE_TIMEOUT_SECONDS` 120→180 merged `24488f4e`. Deploy **#1108** fly-deploy labeled.
- **Prod×main (2026-08-28 2:39 PM MST / 21:39Z, option b, PROVISIONAL):** intended prod SHA **`e86070b`**. No named human approver on the hold — **not** “approved.” Expiry **Sat 2026-08-29 11:52:52 AM MST** (18:52:52Z). Emergency human-approved rollback/safety still allowed. Do not reconcile-flip for the docs-only SHA delta.
- **Resolver recovery (18:50Z):** persisted stall from 16:56Z cleared. `prediction_resolver=ok`, `consecutive_failures=0`. Ops truth = persisted `/api/liveness` + `/api/ops/readiness` (ignore web `/api/learning/health`).
- **Soak RESTARTED:** Fri 2026-08-28 **11:52:52 AM MST** (18:52:52Z). **#1072** closes **Sat 2026-08-29 11:52:52 AM MST** (18:52:52Z). Prior soak from 8:54 AM MST (15:54Z) contaminated (resolver froze 9:56 AM MST / 16:56Z).
- **Fleet deploy HOLD:** #1064–#1067 + #1093 on main, **not deployed**. Cut after #1072 closes.
- **#1065 Proof Scout:** already merged `cc734681` (v5 rebase task N/A — on main).

## Standing policy

- Fleet is exactly **six** bots: Mission Control, Sentinel, Drift/QA, Market Desk, Proof Scout, Shield. **No Remedy bot.**
- Policy §3.1: critical findings and live / behavior-changing updates need **human approval only when necessary**.
- Automation-first default: **docs, mirrors, and other non-live changes should proceed automatically when green**; reserve human review for live behavior, safety, or other explicit gates.
- Insights **>4h** are suspect.
- **Timezone:** Joshua-facing MC times in **Arizona MST** (`America/Phoenix`). UTC on raw log/Sentry/Fly evidence.
- **One PR per bot**, branch `<issue>-<bot>`.
- Canonical refs: `handoffs/bot-fleet-fanout-2026-08-27.md`, `_ci/mission_control_prompt.md`.
- PR **#1082** merged. Do **not** add files to #1082.
- Do **not** route hydrate drafts **#1073 / #1060 / #1061 / #1018**.
- Extra docs PR **#1085** is **not** this fan-out.
- **Pump-alerts preload stays.** No `fly.toml` topology changes.

---

## Closed / resolved

| Item | Resolution |
|------|------------|
| **#1080** Market Desk | **#1100** shipped (was #1088). `trust.ready` gated on `pump_ladder` liveness + signal snapshots. |
| **#1072** Sentinel | **#1089** merged+deployed; formal close after soak ends 2026-08-29 ~15:54Z. |
| **#1078** Drift/QA liveness | Via **#1086** merged 2026-08-28T07:32:58Z (head `6ee50f4b`) |
| **#1079** Drift/QA hour-slot | Via **#1090** merged 2026-08-28T07:33:16Z (head `26067c48`) |
| **#1058** hydration | Live n=3 SHA `ca118843` / Fly `33040064615` |
| **#1081** liveness allowlist | **#1095** daily pick + **#1087** remaining schedulers merged → allowlist `[]` on main `bb142c86` |
| **#1064–#1067** fleet bots | **#1066** Sentinel, **#1065** Proof Scout, **#1067** Shield, **#1064** Market Desk merged 2026-08-28. **#1093** docs merged. |
| **#1029** | Via **#1076 + #1077** |

---

## Phase-5 board

Branches off **main `eb36b0fa`** — last verified 2026-08-28 ~18:35Z.

| Issue | Bot | PR | Status | Notes |
|-------|-----|-----|--------|-------|
| #1072 | Sentinel | **#1089** | **Soak (restarted)** | Clean window **Fri 11:52:52 AM MST** → close **Sat 11:52:52 AM MST** (18:52:52Z both). |
| #1078 | Drift/QA | **#1086** | **Merged** | Head `6ee50f4b`. |
| #1079 | Drift/QA | **#1090** | **Merged** | Head `26067c48`. |
| #1080 | Market Desk | **#1100** | **Shipped** | Joshua sign-off. `gate_pump_desk_trust` live. |
| #1081 | Proof Scout | **#1087** | **Merged** | Allowlist `[]`. |
| — | Sentinel bot | **#1066** | **Merged** | Read-only health observer. |
| — | Proof Scout bot | **#1065** | **Merged** | Evidence gather; classify only. |
| — | Shield | **#1067** | **Merged** | Abuse detection; approval-gated remediations. |
| — | Market Desk bot | **#1064** | **Merged** | Phase-2 specialist; explain-only. |
| — | Docs | **#1093** | **Merged** | Automation-first governance wording. |

### Remaining (not executed)

- **F1 [#1113](https://github.com/cryptoreporthub/subnet-dashboard/issues/1113)** stands. FP7: wedge confirmed, join-vs-dead-timer **undetermined** (no #1114). FP8: revive **OBSERVED** (Sentry PYTHON-FASTAPI-A last **1:05:53 PM MST** / 20:05:53Z this gen). **F2 not filed.**
- **P0 snapshot stall** live (`run_at` still **1:18:26 PM MST** / 20:18:26Z, strike **64/2** at **7:02:24 PM MST** / 02:02:24Z). Unrecoverable until deploy/restart. **No further read-only rounds.**
- **P0 #1112** dead `_last_resolver_tick`. Not a vehicle for this stall.
- **P1 cadence** still unproven for the 110-min gap. Resolver timeouts from **19:26Z** this gen (before freeze).
- **Sentinel soak → #1072 close** — ends **Sat 11:52:52 AM MST** (18:52:52Z; same instant as hold expiry).
- **#1060** FAIL CLOSED open. Liveness leg PASS. Hydration G0 un-run.
- Hydrate drafts **#1073 / #1061** untouched. Held **#1074 / #1069 / #1036** untouched.
- **KILL=0 stays.** Expiry: restart = diagnostic; rollback **unverified** whether it restores a boot-started producer; drain non-daemon pool threads first.

---

## Mirror duty (Joshua 2026-08-27)

Joshua asked that every Mission Control **user-visible status** be mirrored:

1. **Ditto MCP** — `save_memory` with `source: cursor-agents-communication` / `Mission Control`
2. **This file** — append a dated entry so Ditto can read status from the repo shared folder

**Token-budget rule:** .cursor/rules/token-budget.mdc was deleted **2026-08-16**. Leftover `ditto-sync` / `model-guide` / `subagent-models` lines are intentional — **do not edit in docs-only mirror PRs** unless a change is specifically needed for automation alignment.

**Grok Bot** product prompt (short chat) is **not** in this repo.

---

## Log entries

<!-- Append dated entries below. Newest first. -->

### Fri 2026-08-28 7:04 PM MST — last read-only round (FP7/FP8)

**No merge / no deploy / no timeout bump / no KILL unmute / no #1060/#1112 close / no #1114.** #1113 stands. Hold expiry **Sat 11:52:52 AM MST** (18:52:52Z). Clock: Arizona MST; UTC on evidence.

**Re-verify:** `run_at` still 20:18:26.392957Z. Same pids 643/649, `SENTRY_RELEASE=e86070b…`. Strike **64/2** at 02:02:24Z (7:02:24 PM MST); 60/2@01:46:24Z → 64/2 is +4 × 240s. No deploy/restart.

#### FP7 — scheduler vs orphan wait

15 threads; stacks readable (kernel only). `comm=python`. Separate pools **confirmed**: snapshot module `_write_executor` (`score-snap-write`) vs resolver **per-tick** `ThreadPoolExecutor()` + `shutdown(wait=False)` (`resolver_scheduler.py:458-499`).

| tid | born UTC | wchan | note |
|-----|----------|-------|------|
| 649 | 19:21:31 | futex_wait | main |
| 664, 703, 1292 | 19:21:39 / 19:21:55 / 19:54:02 | hrtimer_nanosleep | sleepers (guard candidate 664: 240s strikes still fire) |
| 1284 | 19:52:34 | futex_wait | write-start lineage; **still alive** 02:04Z — idle pool vs join **not discriminable** |
| 1489 | 20:00:35.530 | futex_wait | +30ms after timeout |
| 1501 | 20:01:40 | futex_wait | |

APScheduler shared loop is **alive** (resolver still cycling). Guard is **alive** (240s strikes). Snapshot job re-arm not visible in `/proc`.

**FP7 verdict:** WEDGE CONFIRMED, EXACT BLOCKING MECHANISM UNDETERMINED. Not join-proven. Not dead-timer-proven. **No #1114.** Residual stands. #1113 addendum: mechanism undetermined + separate pools.

#### FP8 — revive

Code: **reachable** (`LOOP_STALL_GUARD_ENABLED` unset → default True; worker; not essential-gated; stale file → strike-1).

Logs: Fly buffer empty. Sentry **errors** (not logs dataset): [PYTHON-FASTAPI-A](https://simivision.sentry.io/issues/PYTHON-FASTAPI-A) template `in-place revive attempt -> %s` (payload not interpolated). Last **2026-08-28T20:05:53.399Z** this gen (`worker.py`, release e86070b) — same second as write_timeout cycle-failed. First seen 2026-08-24T15:59:47Z; 18 occurrences. Prior-gen also 18:05:05Z (before 19:21 cutover).

**FP8 verdict: OBSERVED** — last this generation 1:05:53 PM MST (20:05:53Z). Not UNREACHABLE.

#### Residual (expiry carries this; no further read-only rounds)

Freeze = orphaned write completed 20:18:26Z; loop never cycled again; **wedge-confirmed-mechanism-undetermined**; revive **observed** 20:05:53Z (result payload missing in Sentry); #1113 filed; F2 not filed.

#### Joshua (surface, do not decide)

1. Expiry Sat **11:52:52 AM MST**: no auto-rollback, no auto-extend. Rollback weakened. Restart = diagnostic, **drain first** (#1113). Post-restart: writes → transient; absent → file F2; writes-then-stalls → #1113 reproducible.
2. #1060 FAIL CLOSED open. #1112 open. #1113 mechanism issue.
3. KILL=0. Strike 64/2 at 240s.

### Fri 2026-08-28 6:53 PM MST — clock = Arizona MST

### Fri 2026-08-28 6:53 PM MST — clock = Arizona MST

Operator-facing MC times: **Arizona mountain time** (`America/Phoenix`, UTC−7, no DST). UTC remains on Fly/Sentry/git evidence.

Hold / #1072 soak close: **Sat 2026-08-29 11:52:52 AM MST** (18:52:52Z). Freeze `run_at`: **Fri 1:18:26 PM MST** (20:18:26Z). Cutover: **Fri 12:21:31 PM MST** (19:21:31Z).

### 2026-08-29 ~01:46 UTC — revive vs deploy boundary (FP4–FP6); F1 filed #1113

**No merge / no deploy / no timeout bump / no KILL unmute / no #1060 or #1112 close.** F2 **not** filed. Hold `e86070b` **PROVISIONAL** expiry **Sat 11:52:52 AM MST** (18:52:52Z). Single-agent class.

**Re-verify:** `run_at` still `2026-08-28T20:18:26.392957Z`. Same pids/release. Strikes **observed** 59/2@01:42:24Z → **60/2@01:46:24Z** (exactly 240s = `LOOP_STALL_GUARD_INTERVAL_SECONDS`). Do **not** treat “~54/2 by 01:22” as observed; 4.0/strike **is** observed in this window. `KILL=0`. `SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS=480` on pid 649.

Strike-rate backward date ~21:49:51Z remains an **extrapolation** from earlier 2-interval fit; FP4 did not treat it as a measured first-strike.

#### FP4 — thread forensics

`/proc/649/task`: **15** threads, all `comm=python`, all state **S**, none **D**. Birth windows ±2min **20:18:26Z: n=0**; ±2min **21:49:51Z (extrap): n=0**.

Nearby births: tid **1284** **19:52:34Z**; tid **1489** **20:00:35.530Z**; tid **1501** **20:01:40Z**.

**Limitation:** Python 3.12 thread names did not appear in `comm`; revive `run_once` would not birth a thread at success time. Absent-both windows ≠ inherited.

**Crash/timeout pass (Sentry, not inherited):** `score snapshot write timed out after 480s` **20:00:35Z** (PYTHON-FASTAPI-X); `cycle failed: write_timeout_480s` **20:05:53Z** (PYTHON-FASTAPI-Y). 19:52:34+480s = 20:00:35 **exact**. Late soul success **20:18:26Z** matches an **unjoined write completing after timeout** (`write_full_universe_snapshot` `:318-322` does not cancel `fut`; `_register_write_completion_callback` can persist late success). Rules out “never spawned this generation.” Durable row: **timestamps only**, no writer/instance/machine (`:586-606`).

**Revive preconditions:** ENABLED, worker mode, boot grace, snapshot **age**. **No** essential/heavy skip. Age **None** → reset, **no** revive (`:178-181`). Stale file **does** revive strike-1 once.

**FP4 verdict:** not “live named producer loop since 20:18.” Producer **did run** this gen (timeout then late ok). Freeze after late complete. Revive-vs-inherited **split:** inherited **ruled out**; which entry started the write (revive vs other) still **unverified** (no revive log line).

#### FP5 — deploy boundary

**a.** Fly release **v2095** `CreatedAt` **19:21:10Z**; pids **19:21:31Z**. **Before** 20:18:26Z → row written on the **live** generation. GitHub Actions run **33203293244** exact completion: **GAP** (`gh` 401); Fly timestamp used. `e86070b` git author 19:18:06Z is **not** the cut.

**b.** Prior Fly **v2094** 19:19:55Z (image `01M14VHVDA…`). Runtime `WORKER_HEAVY` of that dead process: **unrecoverable**. `fly.toml` `WORKER_HEAVY=essential` at `e86070b`, parent, and `fe002bb0`. **Regression-vs-structural for this cutover: e86070b is docs-only** (1-line MC log). Rollback **unverified whether it would restore a boot-started producer.**

**c.** Heavy-gate `if heavy: _start_score_snapshot_scheduler()` = `fe002bb0` **#906** 2026-08-13. Before that, `abcf7608` started snapshots **unconditionally**. Prod toml has been essential since **2026-07-24** (`ebd68552`). After #906, **boot** start on prod requires `WORKER_HEAVY=full` (not current `/proc`).

#### FP6 — log window 20:18–21:00Z

Fly `logs --no-tail` buffer: **no** `in-place revive attempt ->`, no `score snapshot cycle ok` in current tail. **Sentry errors** cover 20:00:35 / 20:05:53 write timeout and resolver `cycle_timeout_180s` at **20:13:16Z** (before freeze). First-tick timeout this gen: **19:26:42Z** `cycle_timeout_90s`. Sentry **logs** dataset: no hits for those message strings. Limitation: Fly history for 20:18–21:00Z not in buffer; Sentry errors used as substitute.

#### Filings

| ID | Fire? | Issue |
|----|-------|--------|
| **F1** | **YES** | **[#1113](https://github.com/cryptoreporthub/subnet-dashboard/issues/1113)** — unjoined pools: snapshot `write_timeout_480s` + resolver `cycle_timeout_*`; 3.12 executor threads non-daemon |
| **F2** | **NO** | This gen **did** produce 20:18:26Z; e86070b did not change the heavy-gate; revive not essential-gated. Boot gap is #906-era **structural**, not this cutover. Do not file a false “no snapshot since cutover.” |

#### Decision items (surface, do not decide)

1. Expiry **Sat 11:52:52 AM MST** (18:52:52Z): no auto-rollback, no auto-extend. (a) freeze ≠ cutover boundary (cut 12:21 PM MST / 19:21Z, write 1:18 PM MST / 20:18Z this gen). Rollback **unverified** as restoring boot-start. (b) restart = cheapest diagnostic; **drain first** — 3.12 `ThreadPoolExecutor` threads are **non-daemon**; snapshot write + resolver cycle orphans can hang exit. Post-restart: if producer absent → confirms boot gap (would then be F2-shaped); if it writes then stalls → F1 hang. (c) KILL=0; strike **60/2** observed, 4 min cadence, frozen field.
2. #1060 liveness leg PASS; G0 un-run; FAIL CLOSED open. #1112 open, not this stall. **#1113** is the F1 record for expiry.
3. KILL stays 0.

### 2026-08-29 ~01:22 UTC — snapshot freeze writer vs process wedge (FP1–FP3, no filing)

**No merge / no deploy / no timeout bump / no KILL unmute / no #1060 or #1112 close / no filing** (stop condition did not fire). Hold `e86070b` **PROVISIONAL** expiry **2026-08-29 18:52:52Z**. Evidence class: `/proc` + file:line + git grep on `cfbe842a`/`e86070b` = **single-agent**.

**Re-verify at run start:** `run_at` **still** `2026-08-28T20:18:26.392957Z` at 01:22:09Z. Same `SENTRY_RELEASE=e86070b034011c…`, same pids **643/649**, start **19:21:31Z**. No in-generation revive recovery; no early deploy/rollback.

**G0 timestamp check (do not reuse B's "predates freeze" as settled starvation):** `artifacts/g0-baseline/resume-prod-{1,2}/summary.json` `captured_at` = **2026-08-28T19:51:50Z** and **19:56:36Z** (hero 2.422s / 7.593s). That is **after** boot 19:21:31Z and **before** freeze 20:18:26Z — not ~23:17Z. Hits **web**. Worker `heavy_job_gate` remains in-process; G0 still cannot hold pid 649's lock. Pattern sighting 07:10Z prior generation: **not found in-repo**; cite as unconfirmed sighting only.

#### FP1 — who wrote 20:18:26Z

**a. Boot ordering.** Pid 643 start **19:21:31.040Z**, pid 649 **19:21:31.070Z**, `/proc/1` **19:21:31.453Z**. Fly machine last updated 19:21:31Z (deploy **33203293244** → `e86070b`). **boot < 20:18:26Z** → producer **RAN this generation**. Snapshot age at 01:22:09Z = **18223s**. Frozen row still `ok: true`, count 40, `written_at` 20:18:26.271Z vs file mtime 20:18:26.344Z vs `run_at` 20:18:26.392Z (~48–121ms) — **completed cycle**, then stopped cycling.

**b. Writer grep** (`cfbe842a` ≡ `e86070b` for these lines):

| Site | Guard |
|------|--------|
| `background_boot.py:491` → `_start_score_snapshot_scheduler` | `if heavy:` only (`:487-491`). Essential skips it. |
| `background_boot.py:294` | inside that helper; `SCORE_SNAPSHOT_BOOT_IMMEDIATE` default `on` if worker |
| `score_snapshots.py:719` | `revive_score_snapshot_scheduler` → `start_score_snapshot_scheduler(immediate=False)` then `run_once` |
| `loop_stall_guard.py:114-119` | strike-1 `_try_revive` → revive (worker mode only) |
| tests | `test_background_boot.py`, `test_score_snapshots.py`, `test_loop_stall_guard.py` |

No other prod callers of `start_score_snapshot_scheduler` / `_start_score_snapshot_scheduler`. No HTTP/`write_full_universe_snapshot` caller outside `_tick_body` + tests.

**run_at WRITE SITE:** `_tick_body` persists `run_at=started_at` with `phase=scoring` at **cycle start** (`score_snapshots.py:539-540`), then overwrites with success/fail `run_at=_now_iso()` **after** `write_full_universe_snapshot` (`:558-566`). Frozen row has `ok: true`, `phase: null` → **success persist**, not the start-of-cycle scoring row. Residual "pre-first-write wedge indistinguishable from never-started" does **not** apply to this freeze row.

**c. Host process:** stall guard + revive run only in worker mode (`loop_stall_guard.py:138-140`). Essential boot does not start the producer on 649 or 643 (`BACKGROUND_ON_WEB=off`). The only remaining prod start path that can write **this generation** is **strike-1 revive on pid 649**. Fly log buffer still has no `in-place revive attempt ->` (first strike hours outside buffer) — path is **code-complete**, revive **event** unverified. After that start, producer is **in-process with the resolver on 649**.

**FP1 verdict: case (1).** Start path found (revive, not essential boot). Freeze narrows to **loop-stopped / hung-tick / subsystem wedge after a completed cycle**. Not case (2) contradiction. Not case (3) (this generation booted **before** 20:18:26Z). Stop condition **does not fire**.

#### FP2 — wedge correlation

20:18:26Z sits ~34 min inside the 19:44:44Z→21:07:20Z (82.6 min) last_success gap; cadence then 34.8 → 110. Producer on **pid 649 with the resolver**. Resolver persists after freeze (21:42 / 23:32 / 00:05 / 00:26 / persist 01:15:06Z) falsify a whole-process death.

**FP2 verdict (one sentence):** **SUPPORTED** that a shared-loop / subsystem wedge on pid 649 at ~20:18:26Z stopped snapshot cycling after a completed cycle while the resolver loop stayed alive but degraded — last_success times are persists, not tick times, so simultaneity is inferred.

#### FP3 — what `duration_ms=220709` measures

**(a) worker cycle duration, not the stall guard.** `resolver_scheduler.py:298` `tick_started=time.perf_counter()` at `_tick` entry; `:367` logs `duration_ms` after `_run_refresh_cycle_with_timeout()` returns. Timeout path: `fut.result(timeout=RESOLVER_CYCLE_TIMEOUT_SECONDS)` around `_run_refresh_cycle` (grade due predictions) on a 1-thread pool (`:433-499`); on timeout the scheduler **does not join** the orphan thread (`pool.shutdown(wait=False)`). `cycle_timeout_180s` + `duration_ms=220709` means the **`_tick` frame** ran ~40s past the 180s budget (timeout wait + abandon/persist/log). Named phase: **`_run_refresh_cycle`** (un-joined after timeout). Matches the slow-handler family (`/api/learning/health` 20s, liveness curls 16–28s); **not** a stall-guard checker duration.

#### Decision items (surface, do not decide)

1. Hold expiry **18:52:52Z**: no auto-rollback, no auto-extend. (a) freeze **unrecoverable until next deploy/restart** (one-shot revive spent `:197-199`); (b) restart = cheapest diagnostic — producer healthy post-restart → transient hang; producer absent → boot-config gap (essential omits `_start_score_snapshot_scheduler`), then file; (c) KILL=0 — strikes climbing against a frozen field; unmute = `os._exit(1)` restart loop.
2. #1060: liveness leg PASSES (00:05:15Z → 00:26:47Z, ~5.4 min spacing disclosed); hydration G0 un-run; FAIL CLOSED, stays open. #1112: open; **not** a vehicle for this stall.
3. KILL stays 0.

### 2026-08-29 ~00:30 UTC — snapshot-stall vs cadence (A2a first, B before A3)

**No merge / no deploy / no timeout bump / no KILL unmute / no #1060 or #1112 close.** Hold `e86070b` **PROVISIONAL** expiry **2026-08-29 18:52:52Z**. Evidence class: `/proc` + file:line + Fly persist = **single-agent**.

**Incident wording (unchanged):** post-deploy 15-minute freshness-contract violation is evidenced. It does **not** establish scheduler-fail-to-execute vs health/persist-fail-to-publish.

**Standing constraint:** `LOOP_STALL_GUARD_KILL=0` on pid 643 and 649 (`/proc` 00:25:17Z). Strike **40/2** at 00:26:13Z (`age=14866s`). Enabling kill would `os._exit(1)` into a restart loop driven by the frozen snapshot field. **KILL=0 stays.**

#### Probe A1 — `run_at` still frozen (YES)

At **00:25:34Z** (persist) / **00:28:47Z** (re-read):

- `score_snapshot_scheduler.last_cycle.run_at` = **2026-08-28T20:18:26.392957Z** (`ok: true`, count 40)
- `score_snapshots.json` mtime **20:18:26.344Z**, age **14811s** (~4.11h) at 00:25:17Z
- `liveness.score_snapshot`: `last_success_epoch` = 20:18:26, `lifecycle=started`, skips=0, failures=0, `updated_at` **20:18:29Z**
- Guard 00:26:13Z: `snapshot STALE age=14866s threshold=5400s strike=40/2` `kill=False`

Live second stall. Freeze window at least **20:18:26Z → 00:28Z+**. No recovery.

#### Probe A2a — call-site existence FIRST (NOT orphaned)

`revive_score_snapshot_scheduler` **is referenced** on `origin/main` / prod `e86070b`:

- def: `internal/council/score_snapshots.py:673`
- prod call: `internal/loop_stall_guard.py:114-119` (`_try_revive` when `consecutive_stale == 1 and not revived`)
- tests: `tests/test_loop_stall_guard.py`

**Not** “#1015 never wired.” **Not** a second victim of the #1090 `_last_resolver_tick` rename. **Do not** fold this stall into #1112 as evidence #2 on that theory.

Fly log buffer (`flyctl logs --no-tail`) had **no** `in-place revive attempt ->` line (first strike is hours outside the buffer). Revive result unverified.

#### Probe A2b — gate (wired; not the #1112 dead tick path)

Revive is **not** gated on `_resolver_tick_age_seconds` and **not** gated on `LOOP_STALL_GUARD_KILL`.

It is **once per process lifetime**, strike 1 only (`loop_stall_guard.py:197-199`). Later strikes only log + would-kill. If `_TICK_ACTIVE` / `_tick_active` is set, revive returns `tick_in_progress` without recycle (`score_snapshots.py:706-713`). Hung `_tick_active` also skips persist on later `_tick` (`:443-448`) — that **would** freeze `run_at` at last success. **Unverified in-process** (exec is a new pid; cannot read worker memory).

#### Probe B — shared-process starvation (NOT supported as the boot story)

B1. pid **649** `python -m internal.worker` `RUN_MODE=worker` hosts the **resolver** (heartbeat live). pid **643** is web (`BACKGROUND_ON_WEB=off`).

B2. `WORKER_HEAVY=essential` on **both** pids. `start_background_workers(heavy=False)` **does not** call `_start_score_snapshot_scheduler` (`background_boot.py:487-491`; asserted in `tests/test_background_boot.py`). Web does not start it either (`BACKGROUND_ON_WEB=off` → lifespan skips `start_background_workers`). `heavy_job_gate` is an **in-process** lock. Hydration G0 hits web and **cannot** hold the worker gate; G0 also predates last snapshot success 20:18:26Z.

B3. **Not SUPPORTED** that one busy gate on pid 649 starved **both** schedulers from boot: they are **not co-started**. Resolver is on 649; snapshot producer is **omitted from essential boot** on both processes. After a strike-1 revive, the producer **would** be created in-process on 649 — that post-revive world is unverified (no revive log). Do **not** treat this as two proven independent hung threads either.

#### Probe A3 — filing verdict (after A2 + B)

**No new GitHub issue this session.**

| Branch | Result |
|--------|--------|
| A2a orphaned | **No** — call site exists |
| A2b dead tick / KILL=0 as the revive gate | **No** — different gate (one-shot strike 1) |
| B shared starved process | **Not supported** at boot |
| Gate-logic bug filing | **Do not file** (would manufacture the wrong diagnosis) |
| #1112 umbrella + snapshot as evidence #2 | **Do not** — orphaned-reviver theory failed |

**Reportable residual (not a probe-loop trigger):** who wrote 20:18:26Z on this process generation (revive `run_once` vs unknown); whether `_TICK_ACTIVE` is stuck; Fly log buffer lacks the revive line. Code+env observation (not filed): stall guard watches an artifact whose producer is not in the essential boot set.

#### Probe C — counters (current window leans fork A; 110-min gap still unproven)

Resolver persist 00:28:47Z: `consecutive_failures=0`, skips=0, `last_success_epoch` **00:26:47.619Z**, `last_error=null`.

`/api/liveness` T1 **00:24:19Z**: failures=**1**, status=failing, `last_event_at` **00:23:50Z**, `last_success` still 00:05:15Z. Fly log **00:24:00Z** `cycle_timeout_180s` duration_ms=220709. Soul `prediction_resolver_scheduler.last_cycle` **00:26:00Z** `ok: true`. Success resets counters — **0/0 now does not prove silence during 21:42→23:32**. Current window: scheduler **did fire** and timed out, then succeeded → fork A for *this* window. 110-min gap: still no `tick_start`; heavy_job_busy **does** `record_skip` on resolver, but a later success wipes the counter. **Mechanism unproven** for the incident gap.

last_success intervals (not `last_resolver_tick`): 82.6 → 34.8 → **110** → ~33 (00:05:15) → **~21.5 min** (00:26:47). Still **>15 min**. Not “recovering / hold and observe.”

#### Probe D — #1060 liveness gate retest (against #4/#5, not 21:59Z)

Do **not** cite 21:59:58Z → 22:02:47Z (predates last_success #4).

| Read | `checked_at` | `last_success_at` | status | failures |
|------|----------------|-------------------|--------|----------|
| T1 | 2026-08-29T00:24:19.895Z | 2026-08-29T00:05:15.446Z | failing | 1 |
| T2 | 2026-08-29T00:29:41.317Z | 2026-08-29T00:26:47.619Z | ok | 0 |

**SUCCESS_ADVANCED = true.** Spacing ~5.4 min (spec asked 2–3; first T2 curl at 00:28:21Z **timed out 25s / 0 bytes**, retry 45s / 28.5s succeeded). Liveness **leg passes**. Hydration G0 **not** re-run. **#1060 stays OPEN / FAIL CLOSED.**

`/api/liveness` remains slow (T1 app dur 16.1s; T2 28.5s; one 25s 0-byte timeout). Carry-forward: `/api/learning/health` 20s timeout.

#### Copyable report (Joshua)

Ruled out: (1) snapshot reviver orphaned / #1015 never-wired; (2) snapshot stall as #1112 evidence #2; (3) G0 holding the worker `heavy_job_busy` lock; (4) 5968s as resolver tick; (5) both schedulers co-started on pid 649 at boot; (6) filing a gate-logic bug for this stall.

Residual: freeze mechanism after 20:18:26Z (`_TICK_ACTIVE` / one-shot revive / producer omitted from essential boot). Cadence 110-min gap still unproven; current cycles fire and can `cycle_timeout_180s`. Hold expires **2026-08-29 18:52:52Z** — do not auto-rollback or auto-extend; surface the decision. KILL stays 0.

### 2026-08-28 ~23:44 UTC — P0 stall-guard input vs P1 cadence (read-only)

**Priority (explicit, not equal):**
1. **P0 stall-guard thread** — correctness bug for **every** future resolver stall this guard is supposed to catch. Independent of this incident. Filed **[#1112](https://github.com/cryptoreporthub/subnet-dashboard/issues/1112)**.
2. **P1 cadence thread** — explains **this** incident only. Execution confirmed, mechanism **unproven**.

**Incident wording (unchanged):** Evidence proves a post-deployment 15-minute freshness-contract violation. It does **not** establish scheduler-fail-to-execute vs health/persist-fail-to-publish.

**No merge / no deploy / no timeout bump / no #1060 close.** Hold `e86070b` **PROVISIONAL** (approver ___ none named) expiry 2026-08-29 18:52:52Z. Fly Deploy **33203293244** → `e86070b` Success.

**Evidence class:** `/proc` and file:line reads are **single-agent**, not independently verified, **not** more final than each other.

#### Probe 1a — SET-vs-READ (FIRST)

**Verdict: PERMANENT dead path.** `_last_resolver_tick` is **never SET** and has **no `def`** on `origin/main` `cfbe842a` or prod `e86070b`. Repo-wide: no `_last_resolver_tick =`. Not intermittent.

Removed (not aliased) in `98677e74` (#1090): `def _last_resolver_tick` → `def _resolver_liveness_view`. Callers not updated. Originally `40a6dc27`.

`except → fallback` fires **100%** of calls (`ImportError`). Three reads were a sample; SET-grep is the existence proof.

#### Probe 1b — what 5968s actually is

Log `21:57:54Z snapshot STALE (age=5968s, threshold=5400s, strike=3/2)` is **score-snapshot age**, not `last_resolver_tick` and not liveness `last_success_at`.

- soul `score_snapshot_scheduler.last_cycle.run_at` = **2026-08-28T20:18:26Z**
- 21:57:54Z − 20:18:26Z = **5968s exact**
- Code: `loop_stall_guard.py:160,189` `_snapshot_age_seconds()` vs default max 5400s

Resolver input `_resolver_tick_age_seconds()` (`:82-102`) **always returns None** (1a). Fallback does **not** yield 5968s; it yields **None**, so resolver-stale warn and `_try_revive_resolver` **never run**.

#### Probe 1c — strike 3/2 kill=False

- `LOOP_STALL_GUARD_CONSECUTIVE_CHECKS` default **2** (env `<UNSET>` on pid 649/643 at **23:42:46Z**, single-source `/proc`)
- Strike 3/2 (later **29/2** at 23:42:07Z) ≥ threshold → would `os._exit(1)` **if** `KILL_ENABLED`
- Prod `/proc`: **`LOOP_STALL_GUARD_KILL=0`** (code default True; Fly override). Log: `kill disabled, would have exited`
- Kill is **snapshot-consecutive**, not resolver-age. A working `_last_resolver_tick` would **not** by itself change kill while KILL=0. It **would** re-enable resolver revive after 1800s — currently **inert**

#### Probe 2 (P1) — cadence mechanism still unproven

Worker pid **649** alive (heartbeat 23:42:36Z). last_success **#4: 23:32:05.836Z** (persist + `/api/liveness` 23:43:00Z `ok`, failures=0). last_success **interval** 21:42:08Z → 23:32:05Z = **110.0 min** (not sub-15; **not** “recovering”). Prior intervals 82.6 then 34.8. Fork A vs B **undecided**: no `resolver lifecycle event=tick_start` in `flyctl logs --no-tail` window. Persist still proves cycles complete (success + earlier `cycle_timeout_180s` at 22:01:14Z). Do not call probe done.

#### Probe 3 — not re-run

Carry-forward: persist + `/api/liveness` move together; `learning_loop_health.last_resolver_tick` stale projection. `/api/learning/health` timed out 20.0s at 21:59:21Z — still flagged.

#### #1060

FAIL CLOSED, **stays OPEN**. Hydration G0 not re-run. Last 2–3 min liveness pair (21:59:58Z → 22:02:47Z) did not advance last_success.

**Separate filing:** [#1112](https://github.com/cryptoreporthub/subnet-dashboard/issues/1112) — blast radius inline. Do not close with #1060.

**Deviations:** none. Did not unmute `LOOP_STALL_GUARD_KILL`.

### 2026-08-28 ~22:04 UTC — cadence vs persistence (read-only probes)

**Incident wording (corrected):** Evidence proves a **post-deployment 15-minute freshness-contract violation**. It does **not** yet fully establish whether the worker scheduler fails to execute vs the health/persistence path fails to publish. See probes.

**No merge / no deploy / no timeout bump / no issue close.**

**Non-main prod hold (fill):**
| Field | Value |
|-------|--------|
| approver | **___ none named** |
| timestamp | n/a |
| approved SHA | `e86070b` |
| reason | option-b docs-only delta after #1108 fail; soak time-box |
| expiry | **2026-08-29 18:52:52Z** |
| label | **PROVISIONAL** (not approved) |
| emergency | hold does **not** block human-approved rollback/safety |

**Deploy truth:** Fly Deploy run **[33203293244](https://github.com/cryptoreporthub/subnet-dashboard/actions/runs/33203293244)** (`fly.yml` pull_request, **Success**, Deploy app 3m 34s, checkout **`e86070b`**, triggered 2026-08-28 19:18Z). Prior “gh 401” was **local gh auth**, not a GitHub evidence gap.

**`/proc` timeout (single-agent; MC independent verify: NO):**
- Machine `7841024b3712e8`; worker pid **649** `python -m internal.worker`; web pid **643** `python scripts/run_web_with_guard.py`; start **19:21:31Z**
- `RESOLVER_CYCLE_TIMEOUT_SECONDS=180` from `/proc/{649,643}/environ` at **2026-08-28T21:33:30Z** (prior session). Confidence: **high, SINGLE-SOURCE**.

#### Probe zero — is `last_resolver_tick` a dead metric?

**Not dead.** JSON field **is written** on every `build_learning_loop_health()`:

| Site | Role |
|------|------|
| `internal/learning/loop_health.py:457` | **WRITE** of response key `last_resolver_tick` ← `resolver.get("at")` |
| `internal/learning/loop_health.py:303` | **WRITE** of `at` ← `success_at or event_at` from LivenessTracker snapshot |
| `internal/liveness.py:293` `record_success` / `:366` `_save` | **WRITE** of persisted `soul_map.json` `liveness.prediction_resolver` |

**Not** schema-only. Conditions: `_resolver_liveness_view()` (`loop_health.py:247`) snapshots `get_tracker("prediction_resolver")` then **weak-merges** persisted registry only if in-process status is `no_success_yet`/`failing` or `last_success_at` is missing — **not** if in-process is merely stale. `build_liveness_registry` (`liveness.py:141`) **does** prefer fresher persisted timestamps.

Related (not “no write”): `def _last_resolver_tick` **does not exist**. Callers `internal/learning/routes.py:1285`, `internal/council/resolver_scheduler.py:737`, `internal/loop_stall_guard.py:87` import it and **except → fallback**. That path is dead; the **JSON field** still writes via `_resolver_liveness_view`.

**Do not merge this field into #1060.** #1060 stays hydration + **liveness last_success advancing**. Frozen `last_resolver_tick` is a **projection split**, not a close/fail of G0 hydration.

#### Probe one — worker cadence (third `last_success`)

Worker identity (volume heartbeat **21:57:57Z**): pid **649**, `run_mode=worker`. Process start **19:21:31Z**. Scheduler code: `_tick` logs `tick_start`; skip `heavy_job_busy`; success → `record_success`; else `record_failure` / `record_skip` (`resolver_scheduler.py:294-343`). Refresh 15 min; timeout 180s loaded.

**`last_success_at` values (do not call these a “tick delta”):**

| # | last_success_at | last_success interval vs prior | notes |
|---|-----------------|--------------------------------|-------|
| 1 | 19:44:45.843Z | — | first post-deploy success observed |
| 2 | 21:07:21.800Z | **82.6 min** | one interval; not a trend |
| 3 | **21:42:08.944Z** | **34.8 min** | third success; persist `updated_at` 21:42:12Z; HTTP `/api/liveness` 21:58:25Z matches, `source=persisted` |

Both observed last_success **intervals** (82.6 min, 34.8 min) **exceed 15 min**. n=2 intervals from n=3 successes — repeating vs one-off is **better supported than n=1**, not a full n≥3 interval series.

**Cycle execution between 21:59:58Z and 22:02:47Z (HTTP `/api/liveness`):** last_success **unchanged** 21:42:08Z; status `ok` → **`failing`** (`status_reason`: last tick raised); `consecutive_failures=1`, skips=0. Persist at 22:03:51Z: `last_error=cycle_timeout_180s`, `last_event_epoch` → **22:01:14.934Z**, `updated_at` **22:01:17Z**. Fly log 21:57:54Z: loop stall guard snapshot STALE age=5968s, strike=3/2, kill=False. **Worker did run a cycle that hit `cycle_timeout_180s`.** That is execution, not “never ticks.” Mechanism of the 82.6 min gap still **not fully established** (timeouts, heavy_job skips, and projection lag can all stretch last_success).

Recent `flyctl logs --no-tail` did **not** include `resolver lifecycle event=tick_start` lines (log window may omit worker stdout). Cycle start/end wall times for 21:42 success **not** captured in that tail.

#### Probe two — persist vs health projection

| Source | Read timestamp | last_success / last_error | last_resolver_tick |
|--------|----------------|---------------------------|--------------------|
| soul_map `liveness.prediction_resolver` | 21:57:56Z then 22:03:51Z | 21:42:08Z; later fail `cycle_timeout_180s` @ 22:01:14Z | n/a (field not stored) |
| GET `/api/liveness` | 21:58:25Z / 21:59:58Z / 22:02:47Z / 22:03:31Z | matches persist (21:42:08Z; then failing) | n/a |
| GET `/api/ops/readiness` `resolver` + nested `liveness` | 21:58:25Z | matches persist 21:42:08Z | — |
| GET `/api/ops/readiness` `learning_loop_health` | 21:58:25Z | `resolver.last_success_at` **19:16:36Z** | **19:16:36Z** (unchanged all session) |
| GET `/api/learning/health` | 21:59:21Z (app log: timed out after 20s) | null / degraded | null |

**Conclusion (bounded):** **Worker persist + `/api/liveness` are moving together.** **`learning_loop_health.last_resolver_tick` (and that object's `resolver.last_success_at`) are a stale HEALTH PROJECTION**, consistent with weak merge in `_resolver_liveness_view` vs full merge in `build_liveness_registry`. Does **not** prove the worker never ran.

#### #1060

Two liveness reads **2.5 min apart** (21:59:58Z → 22:02:47Z): last_success **did not advance** (21:42:08Z both). **FAIL.** Hydration G0 2.422s/7.593s on this SHA still stands; not re-run. **Leave #1060 OPEN.** GitHub closed #1058/#1072 is not this gate.

**Deviations:** none (read-only). Hold labeled **PROVISIONAL**.

### 2026-08-28 ~21:39 UTC — prod×main reconciliation + resolver evidence gates

**No merge, no prod deploy, no timeout bump this session.**

#### Gate 0 — prod×main reconciliation (blocking)

| Item | Live |
|------|------|
| `origin/main` | `cfbe842a` (2026-08-28 19:15:08Z local / 12:15:08 -0700) #1109 |
| Prod SHA | `SENTRY_RELEASE=e86070b034011ca97af95ebe5e64ed593bd69124` (`/proc/649` + `/proc/643` at **2026-08-28T21:33:30Z**) |
| Relationship | `cfbe842a` **is ancestor of** `e86070b`. `e86070b` **not on main**. `git log main..e86070b` = 1 docs-only commit (`mission-control-log.md` +1). `git log e86070b..main` = empty. Tree of `e86070b` **==** `#1110` commit `57a7b18f`. `#1110` HEAD `47db090` is `e86070b` + 7 more MC-log lines — **not** what is running. |
| Product delta vs main | **none** for `fly.toml` / resolver: both have `RESOLVER_CYCLE_TIMEOUT_SECONDS=180`. |

**Decision (b), not (a):** do **not** promote `cfbe842a` to prod now.

- **Why `e86070b` is the intended prod release:** legitimate PR-triggered path after #1108 Deploy-app **FAIL** (run **33201296527**). #1110 (`cursor/fly-deploy-1107-retry-f603`) carried the #1107 timeout onto a deployable SHA. Fly **v2095** complete **2026-08-28T19:21:10Z**; machine `7841024b3712e8` updated **19:21:31Z**; kernel `btime` **19:21:30Z**; web pid **643** + worker pid **649** started **19:21:31Z**. Git commit timestamp **19:18:06Z** is **not** the deploy instant.
- **Why not (a) now:** promoting `cfbe842a` is a machine restart for **zero** resolver/product delta vs `e86070b`, forbidden while evidence gates were open, and would contaminate the soak.
- **Time-box:** intended SHA stays **`e86070b` until 2026-08-29 18:52:52Z** (soak / #1072 close target). Next **authorized** Fly deploy must be `origin/main` (or main fast-forwarded to include this docs commit) so prod == main. Until then the divergence is **recorded, not silent**.
- **Workflow-run evidence:** #1108 Deploy app **33201296527** ❌. #1110 PR checks show smoke **33203323484** ✅ only (HEAD `47db090` — later than deployed SHA). **GAP:** GitHub `gh` 401 — cannot list `fly.yml` run that produced v2095. Deployment truth used instead: Fly release timestamp + process start + `/proc` `SENTRY_RELEASE`.

#### Gate 1 — is 120→180 loaded in the running process?

| Item | Value |
|------|-------|
| Verdict | **YES — 180 is loaded** |
| Method | `flyctl machine exec 7841024b3712e8` read `/proc/649/environ` (cmd `python -m internal.worker`) and `/proc/643/environ` (`python scripts/run_web_with_guard.py`) |
| Timestamp | **2026-08-28T21:33:30Z** (reconfirmed with start times **21:34:56Z**) |
| Worker | pid **649**, `RESOLVER_CYCLE_TIMEOUT_SECONDS=180`, `RESOLVER_REFRESH_MINUTES=15`, `SENTRY_RELEASE=e86070b…` |
| Web | pid **643**, same timeout/SENTRY |
| Process start | **2026-08-28T19:21:31Z** (both pids; uptime ~8005s at 21:34:56Z) |

No further timeout bump. Value is 180 in the live worker, not only `fly.toml`.

#### Gate 2 — freeze timeline vs 19:18:06Z

**19:18:06Z is the git author time of `e86070b` / first #1110 commit. Process-start / Fly cut is 19:21:31Z / v2095 19:21:10Z.**

| Clock | Event |
|-------|--------|
| **19:16:36Z** | `learning_loop_health.last_resolver_tick` last value (still frozen at 21:38Z) — **BEFORE** 19:18:06Z |
| 19:18:06Z | git commit `e86070b` / `57a7b18f` (same tree) |
| 19:18:13Z | PR #1110 opened |
| 18:53–18:56Z | #1108 Deploy app FAIL **33201296527**; Fly releases 2090–2092 in this window |
| 19:19:09–19:20:57Z | #1110 smoke **33203323484** |
| 19:19:27 / 19:19:55 / **19:21:10Z** | Fly releases 2093, 2094, **2095** (current image `deployment-01M14X1RNN9Q9WBG967YHVFNZ2`) |
| **19:21:31Z** | worker+web process start (pid 649/643) |
| **19:44:45Z** | persisted `prediction_resolver.last_success_at` — **AFTER** deploy |
| **20:01:08Z** | skip event (`consecutive_skips=1`); last_success **did not** move — ~16.4 min after 19:44:45 (≈15m refresh) |
| **21:07:21Z** | last_success advanced again (post-skip recovery) |
| 21:35:36Z READ1 | last_success still **21:07:21Z**, status `ok`, age 1700s |
| 21:38:37Z READ2 | last_success **unchanged**, status **`stale`**, age 1877s; `last_resolver_tick` still **19:16:36Z** |

**Causality:**

1. `last_success_at` freeze observed 19:50–20:06Z: **freeze_start = 19:44:45Z > 19:18:06Z** and **> 19:21:31Z**. Deploy did **not** start that freeze; a **post-deploy success** then a skip at 20:01:08Z did.
2. `last_resolver_tick` (loop_health): **freeze_start ≤ 19:16:36Z < 19:18:06Z**. Field never caught 19:44:45 or 21:07:21. **Pre-deploy stale web snapshot**, not caused by e86070b.
3. Tick deltas: 19:44:45 → 21:07:21 = **+82.6 min** (not 15 min). READ2 real-time gap vs last_success = **1877s (~31.3 min)** — cadence broken even with 180s timeout loaded.
4. Hypothesis upgrade: **fix present (180 in `/proc/649` from process start) but 15m cadence still not held.** Not “timeout never loaded.”

#### Gate 3 — #1060 (re-pulled)

| Issue | GitHub | Quality |
|-------|--------|---------|
| #1058 | CLOSED 2026-08-27T06:04:59Z (`completed`) on n=3 SHA `ca118843` / Fly **33040064615** | Close was for **#1071** critpath, **not** G0 post-offload bar in #1060. Stale vs this gate. |
| #1072 | CLOSED 2026-08-28T06:15:52Z (`completed`) | Soak restart 18:52:52Z still running — GitHub close ≠ soak complete. |
| #1060 | **OPEN** draft, head `cursor/post-offload-audit-ec01` `7b937797` | Keep open. |

**Current prod evidence (this session):**

- Hydration (same SHA `e86070b`, 19:51/19:56Z G0): hero **2.422s / 7.593s** — still the latest G0 pair; SHA unchanged so not re-run (avoid load during freeze forensics).
- Resolver two reads **2.5 min apart (21:35:36Z → 21:38:37Z):** last_success **did not advance** (21:07:21Z both). **FAIL.**

**#1060 verdict: FAIL CLOSED — leave open. Flag Joshua.** Cadence + stale `last_resolver_tick` remain.

**Deviations:** none new (no deploy, no merge to main, no timeout change). Prior #1110 auto-retry still on record.

### 2026-08-28 ~20:10 UTC — v5 resume: #1060 G0 audit + #1107 prod verify

**Re-verified GitHub (live):**
- **main head:** `cfbe842a` (#1109 docs v5 delegation). **#1107** merged `24488f4e` on main.
- **#1108:** CLOSED, NOT merged. Deploy app **FAILED** run **33201296527** (Deploy Guard ✅, smoke ✅, Deploy app ❌).
- **#1110:** CLOSED (retry deploy PR). CI: smoke only run **33203323484** ✅ — no Deploy app job on PR checks.
- **#1060:** STILL OPEN (draft). **#1058 / #1072:** CLOSED on GitHub.

**Secondary — #1107 on prod (live runtime, not file):**
| Item | Evidence |
|------|----------|
| Deployed SHA | `SENTRY_RELEASE=e86070b` via `flyctl ssh console` (2026-08-28 ~19:52Z). Ancestor of main `24488f4e` + `cfbe842a`; **not** identical to main HEAD. |
| Runtime timeout | `RESOLVER_CYCLE_TIMEOUT_SECONDS=180` via `flyctl ssh console` (confirmed twice). |
| Fly release | **v2095** complete ~19:21Z; machine `7841024b3712e8` last updated 2026-08-28T19:21:31Z. |
| #1108 deploy | Did **not** land #1107; prod reached via separate fly-deploy branch commit `e86070b` ("docs: retry fly-deploy #1107 after #1108 Deploy app failure"). |

**Primary — #1060 post-offload G0 audit (prod `https://subnet-dashboard.fly.dev`, Playwright harness):**

| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | Hero-critical hydration ≤10s (both runs) | **PASS** | `resume-prod-1`: hero **2.422s**, shape HYDRATES_IN_BUDGET, no hero-critical aborts. `resume-prod-2`: hero **7.593s**, same. Artifacts: `artifacts/g0-baseline/resume-prod-{1,2}/`. |
| 2 | `/health` not 8s TimeoutError cliff | **PARTIAL** | Run-1: p95 **411ms** (136/136 OK). Run-2: p95 **1723ms**, p100 **8078ms** (82/84 OK) — one late-window 8s timeout remains under fan-out. |
| 3 | daily-pick does not hold handler | **PARTIAL** | G0 probe: run-1 **373ms** status 200; run-2 **1859ms** status 200. Sequential `curl /api/daily-pick` at ~20:00Z **15s timeout** (machine contended post-G0). |
| 4 | Degraded paths shape-stability | **PASS** | Both runs: final hero `SN107 · Minos`, verdict `sealed`, graded **57**, statsGraded=57 — no placeholder/cold starvation shape. |
| 5 | Resolver tick advancing (2 spaced prod reads) | **FAIL** | Persisted `/api/liveness` `prediction_resolver.last_success_at` frozen **19:44:45Z** from READ1 (19:50Z) through poll-4 (20:06Z) — **no advance** across 16+ min (15m scheduler should have ticked ~19:59Z). Skip event at **20:01:08Z** (`consecutive_skips=1`) without new `last_success_at`. |
| 6 | `last_resolver_tick` in `/api/ops/readiness` | **FAIL (stale field)** | `learning_loop_health.last_resolver_tick` stuck **19:16:36Z** while persisted liveness shows **19:44:45Z** — hydration inconsistency; do not use readiness tick alone. |

**Gate verdict: FAIL CLOSED — do not close #1060.** G0 hydration bar improved vs prior #1060 FAIL (hero 12–15s → 2.4s/7.6s), but resolver advancement criterion not met and readiness tick field is stale. **Flag Joshua.**

**Deviations:** None new this session (prior #1110 auto-retry already flagged).

**Soak:** unchanged — restart **18:52:52Z** → #1072 close **2026-08-29 18:52:52Z**. Fleet deploy still held.

### 2026-08-28 ~19:14 UTC — v5 delegation: #1107 merge + resolver recovery + soak restart

- **#1107 merged** `24488f4e` (RESOLVER_CYCLE_TIMEOUT_SECONDS 120→180). **#1108** fly-deploy labeled.
- **Incident cleared:** stall from 16:56Z; recovery tick **18:50:55Z**, liveness last **18:59:04Z**.
- **Verify (5 criteria):** (1) resolver=ok ✓ (2) readiness ready, loop ok ✓ (3) tick past 16:56Z ✓ (4) tick advanced stall→18:50→18:59; NOT in final 3-min pair (15m scheduler) — watch next cycle (5) consecutive_failures=0 ✓
- **Soak RESTART:** **2026-08-28 18:52:52Z** → #1072 close **2026-08-29 18:52:52Z**.
- **#1065:** already merged `cc734681`; v5 rebase N/A. Fleet deploy held post-soak.
- **Per-bot:** #1066 merged | #1065 merged | #1067 merged | #1064 merged | #1093 merged — all code-only, not on prod.

### 2026-08-28 ~17:10 UTC — #1102 deploy + #1088 governance ship-it

- **Deploy:** #1103 `fly-deploy` → run **33192921483** success. main `cfa7a5bc`.
- **#1088 gate verified:** `/api/ops/readiness` `pump_desk_trust.ready=true`, `pump_ladder=ok`. `/api/pump-alerts` `trust.liveness.status=ok` but `signal_snapshots_stale=true` (trail placeholder rows — gate working as designed).
- **Learning health:** `status=ok`, resolver `ok`, last tick 16:56Z.
- **Governance:** Joshua sign-off #1088→#1100 ship it.
- **Next:** soak through 2026-08-29 15:54Z → close #1072 → G0×2 → #1058.

### 2026-08-28 ~15:48 UTC — Fleet takeover + Fly deploy (#1098)

- **Policy:** Composer owns all six bot roles; bot-directed work routes to Composer. Deploy via `fly-deploy` label (not Joshua-only).
- **Deploy:** #1098 labeled `fly-deploy`; workflow **33186935806 success** (15:52:44Z). `/api/liveness` confirmed on prod.
- **Soak:** Sentinel 24h watch armed through **2026-08-29 ~15:54Z** (`/health`, `/api/ops/live`, wedge window).
- **Parked:** #1088 human-merge-only (behavior change).

### 2026-08-28 ~15:35 UTC — Deploy is the board choke point (Joshua)

- **Gate:** Fly deploy of `main` `c82c59fe` (human `workflow_dispatch` only). Prod still worker pid 650 — bundle is not just #1089.
- **Then:** Sentinel 24h prod soak → close #1072. Optional G0 ×2 → #1058 formal close.
- **Parked:** #1088 human-merge-only. MC continues routine merges to main; main/prod drift expected until deploy cut.

### 2026-08-28 ~13:05 UTC — #1081 liveness complete (#1095 + #1087)

- **Policy:** Joshua not required for routine merges; Composer verifies no conflict + CI green.
- **Merged:** **#1095** (`ebafd329`) DailyPickScheduler → LivenessTracker; **#1087** (`bb142c86`) remaining 7 schedulers + allowlist `[]`.
- **CI:** smoke green on both PRs (runs 33172947439, 33173497469).
- **Tests:** `test_no_handrolled_liveness`, `test_pick_scheduler`, `test_selector_scheduler`, contract guard — green locally.
- **Parked:** **#1088** Market Desk — human merge only. Deploy not triggered (Fly gated).

### 2026-08-28 ~12:50 UTC — Composer takeover (#1081)

- **Policy:** Joshua not required for routine merges; Composer verifies no conflict + CI green.
- **Done:** `DailyPickScheduler` migrated to `LivenessTracker`; `pick_scheduler.py` removed from liveness allowlist (8→7 modules).
- **Tests:** `test_no_handrolled_liveness`, `test_pick_scheduler`, contract guard — green locally.
- **Branch:** `cursor/1081-daily-pick-liveness-f603` — merged as **#1095**.

### 2026-08-28 ~2:22am PT — Sentinel soak (post-#1089 merge)

- `/health` 200, `/api/ops/live` ok `live=true`, homepage desktop+390px 200.
- One recovered 20s ops/live timeout.
- Fly pid 650 unchanged — #1089 on main likely not on the machine. **No deploy.**
- 24h wedge watch armed through 2026-08-28 23:59 PT.

### 2026-08-28 ~1:06–1:08am PT — #1086+#1090 on main

- #1086 merged 2026-08-28T07:32:58Z (head `6ee50f4b`). #1090 merged 2026-08-28T07:33:16Z (head `26067c48`).
- Main SHA verified `98677e74` includes both.
- #1087 `ef3ae950`: leftover cleanup confirmed; `pick_scheduler.py` zero vs main.
- DailyPickScheduler `_running`/`_last_run_at`/`_last_ok` still on main — fails #1087 empty-allowlist smoke.
- Joshua skipped daily-pick follow-on widget; **do not** claim a follow-on is open.

### 2026-08-28 ~12:22am PT — #1087 collision cleared

- Collision cleared at `5c74d609`, then leftover cleanup per Shield.
- Shield re-audits #1087.

### 2026-08-28 ~12:10–12:17am PT — #1086 leak patch

- Leak patch head `6ee50f4b`; smoke green.
- Leak HOLD closed.

### 2026-08-28 ~12:04–12:08am PT — Shield FINAL on #1088; #1090 smoke green; #1086 rebase

- #1088 Shield FINAL HOLD (human merge only).
- #1090 smoke green.
- #1086 rebase done `e6d928df` then leak patch applied.

### 2026-08-28 ~11:58pm PT / 06:58Z — Step 0 complete: #1091 on main

- Un-drafted #1091, updated branch onto main after #1089+#1085 (head 1fc9386a), smoke green (run 33149466727).
- Squash-merged #1091 at 2026-08-28T06:58:26Z as SHA 4d72a1c385d5c0a2d46057809e564daf85c5b76b. Files: mission-control-log.md, ditto-sync.mdc mirror duty, board.md pointer.
- #1089 already merged (closes #1072). #1085 already merged.
- Next: rebase draft #1086 onto this main; fan-out Sentinel soak, Drift/QA #1090, Market Desk HOLD #1088, Proof Scout #1087 (allowlist 7→0), Shield re-audit.
- No Phase-5 bot PRs merged in this step. #1088 remains parked.

### 2026-08-28 ~05:40Z — Initial snapshot

Phase-5 fan-out board seeded from Mission Control handoff. #1089 ready first; #1086–#1090 remain draft / human-gated. Mirror rule added: `mission-control-log.md` + Ditto `save_memory`.
