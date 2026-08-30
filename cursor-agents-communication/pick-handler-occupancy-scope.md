# Pick-handler occupancy — scope plan (2026-08-30)

Answers Ditto GO checklist ([#1136](https://github.com/cryptoreporthub/subnet-dashboard/pull/1136)) plus amendment **v4 (FINAL, supersedes v3)**. **Plan only. No implementation in this PR.**

**Status: M4 PASS on trimmed #1138 — awaiting Joshua M5 (merge AND deploy are one act).**

**Gates (verbatim, receipts `f661435d` / `ditto-occupancy-e1e2-receipts-2026-08-30.md`):**

- Patch F (static composed-lifecycle): SATISFIED with receipts (the #1008 exact-diff item is now closed).
- Patch D (runtime resource capture): OPEN — gates ranks 2/3/(e), NOT rank 1.
- Rank 1 (single-flight GET) remains the ONLY mergeable cut; #1138 must NOT merge as-is; 90s stays; KILL=0; #1112/#1113 untouched; #1060 stays open; #1058 stays closed; no deploy without Joshua.
- B6 wording: keep "No deploy without Joshua" (broader than "no fly-deploy") — retain, don't downgrade.

Companions (not subsections — distinct deliverables; this file stays the **gate surface**):

- [`amendment-occupancy-plan-v4.md`](amendment-occupancy-plan-v4.md) — consolidated patches (PR #1136 head `f8fa3905`)
- [`pr-sequence-regression-analysis-906-1022.md`](pr-sequence-regression-analysis-906-1022.md) — #906→#1022 finding; fold deltas are that doc’s **§6**
- [`ditto-occupancy-e1e2-receipts-2026-08-30.md`](ditto-occupancy-e1e2-receipts-2026-08-30.md) — #1008 exact-diff + E1/E2 source of truth (on `origin/main` `f661435d`)

Line numbers below are re-pinned against `origin/main` **`5a33fe6c`** (code files identical on this branch; see §8). Do not reuse `cfbe842a` ranges without a fresh `git show`. An implementation Go must `git show` **then-current** HEAD again.

**Fix framing (ranks 2/3/(e), after gates):** “**#1008’s goal, completed correctly**” — next tick always starts fresh **and** the previous worker is bounded (join-with-deadline / cooperative cancel / true single-flight). **Not** “restore #906” (reintroduces skip-forever). **Not** design-blind.

## 1. Occupancy (definition + metric)

**Occupancy** = wall-clock from handler/tick entry to return, including every nested call that holds a Python thread or the GIL on the inline web+worker box.

Two sites. Do not collapse them:

| Site | Entry | Cap today | Metric (already exists unless noted) |
|------|--------|-----------|--------------------------------------|
| **GET** `/api/daily-pick` | `api_daily_pick` | `PICK_READ_TIMEOUT_SECONDS` default **0.5s** (env-overridable; prod value still needs `/proc` or env evidence) | middleware `dashboard_request path=/api/daily-pick duration_ms`; optional `DAILY_PICK_STAGE_TIMING=1` (`hydrate_get_*`) |
| **Tick** `daily-pick-scheduler` | `DailyPickScheduler._tick` | `DAILY_PICK_TICK_TIMEOUT_SECONDS` default **90** (do not bump) | add `duration_ms` on `last_tick` in an impl PR; tonight: soul/volume `written_at` − slot 00:15Z |

`/health` p95 during a hydrate burst is the **shared-runtime** blast-radius metric (same 1 vCPU), not a third pick handler.

Three timing envelopes on the tick (do not collapse):

1. **Pre-future** — APScheduler thread: `_load_capped_subnets` + `_market_context` (unbounded vs the 90s cap).
2. **In-future** — 1-thread `daily-pick-work`: `get_or_create_today_pick` → `select_daily_pick`.
3. **Post-timeout** — abandoned worker may still write JSON/HOLD **after** the 90s return (generation guard does not stop writes). See §3 (b1).

## 2. Baseline (tonight)

| Evidence | Value |
|----------|--------|
| 00:15Z tick | 90s timeout → HOLD persisted 00:17Z `scheduler_hold` |
| 00:39Z | directional-conflict HOLD (real decision, not timeout) — **engine can finish inside 90s** |
| G0-1 00:49Z | hero NEVER; UI **pick handler busy — retry shortly**; `/health` p95 **1245ms** / p100 8076ms; ~9 parallel `/api/daily-pick` |
| G0-2 00:54Z | same hero NEVER; then `/health` timeout + liveness 503; recovered 00:57Z no restart |
| Sequential GET (Cursor 00:30Z) | **184ms**, stored timeout HOLD — GET is fast when the box is idle |

So: GET is already off the scoring engine. The screenshot string is the **0.5s read-path timeout**, not `select_daily_pick` on GET. The 90s failure is the **background tick**. The timeout is **long-tail, not baseline**.

**RECURRENCE, NOT A ONE-OFF — AND A SELF-CREATED COMPOSED CONFLICT.** Daily scoring became a traffic-independent essential workload on 2026-07-26 (PR **#500**). By 08-03, PR **#781/#782** already documented the tick “wedges the shared Fly VM”. Subsequent PRs form one lifecycle; the conflict spans their boundaries:

| Date | PR | What |
|------|-----|------|
| 08-13 | **#906** | Overlap protection (`_work_thread.is_alive()`). Guard ADD: `8f158de08` (2026-08-13T12:01:26Z) — skip log `"daily pick tick skipped; previous worker still running"`. PR body (verified 2026-08-30): abandoned executor/thread work starved the worker HTTP process → Fly 8081 health timeout → “Worker volume temporarily unavailable.” Exact guard diff: **verified**. |
| 08-20 | **#1008** | **Intentional** replacement. Causal commit `1eb0a6bfa3` (2026-08-20T22:51:57Z): **removes** the `is_alive()` guard; **adds** `ThreadPoolExecutor(max_workers=1)`, `_work_generation` bump on timeout, `fut.result(timeout=…)`, `pool.shutdown(wait=False, cancel_futures=True)`. Test rename (behavioral receipt): `test_daily_tick_skips_when_previous_work_is_still_running` → `test_daily_tick_timeout_then_immediate_retry_starts_new_worker` (timeout → next tick STARTS a new worker; it does NOT wait for the prior one). Tokens discard zombie **results**; they do **not** bound worker lifetime or side effects. Merge `d3e331aad` (2026-08-20T22:59:07Z) is an ancestor of `5a33fe6c`; incident ~2026-08-30T00:15Z (~9d1h16m gap). **MERGE ≠ DEPLOY** — do not claim deployment. |
| 08-20 | **#1008** VM | Commit `0769f631c8` (2026-08-20T22:21:23Z): fly.toml `shared-cpu-1x` → `shared-cpu-2x` (“Prod emergency: scale v1 web VM to shared-cpu-2x (CPU starvation)”). Current `origin/main` shows `performance-1x` / `4gb`. Resource-topology history is part of the evidence chain. |
| 08-21 | **#1009** | Forced 15-min retry after timeout regardless of abandoned-worker writes (audit; re-verify PR body at impl time). |
| 08-22 | **#1021** | Nested 4-worker scoring executor, non-cancellable. Audit quote from PR: ~20 subnets, **1712s wall / 128 CPU-s** vs 90s budget — re-verify at impl time. |
| 08-22 | **#1022** | Global `_tmc_refresh_lock` — **diff-verified**: “peers block on the lock”; serializes both TMC endpoints; assumes “refresh window is short.” |
| 08-23 | **#1025** | File-locked score cache (`fcntl`) — probably secondary, not primary. |
| 08-28/29 | **#1095/#1128** | Liveness + DateTrigger re-arm: makes the heavy tick run **reliably**; does not fix the workload lifecycle. **#1128** `if still_scheduled:` (diff-verified) — separate contract item, not Aug-30 root without runtime evidence. |

**THE CONFLICT, STATED:** “We intentionally removed the only code that knew whether the previous daily worker was still alive, while preserving automatic retries and adding nested, non-cancellable parallel work behind a shared global lock.” (Replit audit #2 — primary investigation target.)

Tonight’s signature (“pick handler busy” + `/health` 8s + 503) is the **same failure mode #906 was built to fix** — back because #1008 re-opened the daily-pick half of the protection (failure-mode framing, not a resource-level root-cause claim). Recurrence is structural, not coincidence.

The #906 failure mode (#1008 re-opened, #1009/#1021/#1022 amplified) is a code-level causal chain; the exact exhausted resource is UNPROVEN and requires runtime capture (Patch D).

Same-signature recurrences: 08-19, 08-21, 08-25; pump-alerts line degrading since 07-27. 08-29 ~03:00Z: #1087 LivenessTracker wedge (write timeouts leave tick-active flags). Tonight (00:15/00:17Z) is the latest instance.

**00:39Z** directional HOLD: engine **can** finish inside 90s. Consistent with convoy: fast path = early council exit; slow path = full scoring under TMC/cache contention.

Cuts in this plan explain: **08-19 / 08-21 / 08-25 handler-busy HOLDs + tonight’s GET busy + tick abandon**. They do **not** explain: alerts-line degradation, resolver freshness.

## 3. Root-cause map

### GET (hydrate) — `server.py` `api_daily_pick` (`3122-3194`)

Already P1: no `get_or_create_today_pick` / `select_daily_pick`. Dedicated 2-thread `"pick-read"` pool (`629-634`). Flow:

1. `_find_today(_load())` on `_PICK_READ_EXECUTOR`, wait ≤0.5s (`3139-3147`)
2. `_enrich_daily_pick_payload_lite` on the same pool, wait ≤0.5s (`3171-3186`) — names, brief, tribunal fields, web spotlight, judge scores, pump chip. **No live subnet scoring**, but still CPU/GIL. `_to_thread_timeout` (`661`) bounds the await; the executor callable may continue.
3. Timeout on the **read** wait → `_daily_pick_timeout_hold()` (`3096-3106`) reason `pick handler busy — retry shortly` (`status: timeout`, not a scheduler HOLD). Enrich timeout returns stored JSON, not the busy string (`3179-3186`).

**Blocks GET:** JSON `_load`, lite enrich, pick-read pool saturation, GIL vs 20+ other `/api/*` on `_DASHBOARD_EXECUTOR` (top-picks 8s, weighed 8s, hour, subnets). Client retries multiply `/api/daily-pick`.

Daily GET does **not** have hour-pick’s lock. `/api/top-pick/hour` uses `_HOUR_PICK_LOCK` (`648`, `3253-3283`) — cached or `"busy"`. Do not imply daily already has that pattern. TMC single-flight (`internal/indicators/tmc_singleflight.py`) is pre-warmed from `select_daily_pick` (`daily_pick.py:151-158`), not from GET.

Enforced: `tests/test_homepage_pick_read_only.py:36-92` (`_boom` if engine called); `tests/test_pick_scheduler.py:406-409` (GET must stay a read-only hydrate API).

### Tick — `internal/council/pick_scheduler.py` `_tick` (`270-375`)

**(a) Outside the 90s future** (scheduler / APScheduler thread — blocks re-arm):

1. `_load_capped_subnets()` (`276`, def `125`) → `server._get_subnets_with_source()` + cap 24
2. `_market_context()` (`277`, def `138`) → `_market_context_with_weights`

**(b) Inside the 90s 1-thread `daily-pick-work` pool** (`284-302`):

3. `get_or_create_today_pick` (`daily_pick_engine.py:184-327`) → on `scheduler_hold` or miss, `select_daily_pick` (`daily_pick.py:112+`: TMC pre-warm `151-158`, JSON score cache `163-228`, parallel `dpick-score` workers `216-221`)

On `FuturesTimeoutError`: bump `_work_generation` (`215`, `297-298`), log `worker abandoned`, `pool.shutdown(wait=False, cancel_futures=True)` (`302`) — same unjoined-pool motif as #1113; **do not bundle**. Then `write_scheduler_hold`. Retry `DAILY_PICK_RETRY_MINUTES` (15) (`369-372`). Test: `tests/test_pick_scheduler.py:350-393` (timeout retries even if a zombie wrote HOLD to disk).

**(b1) SIDE-EFFECT WINDOW (critical).** Abandoned worker is **not** cancelled (`shutdown(wait=False, cancel_futures=True)` does not stop a running callable — stdlib). `get_or_create_today_pick` can still write `data/daily_picks.json` (`_save` at `241`, `284`) and prediction/HOLD records (`286-325`) **before** the generation check at `_run_pick` (`288-290`) rejects the returned payload. Generation guard stops stale **result** propagation, not writes.

EPISTEMIC STATUS: **triple independent corroboration** — code-forward (source-verified vs `cfbe842a` / re-pin `5a33fe6c`), symptom-reverse (Ditto from 00:49 shared starvation), PR-composition (Replit audit #2 + #906/#1008 PR bodies). Stronger than any single path. Required in any impl PR as a post-timeout side-effect audit.

**(b2) RANK 2 REVERSES CURRENT DESIGN — CONTAINMENT, NOT ROOT FIX.** Today subnet+market load runs **outside** the 90s future on the APScheduler thread (`276-277` **before** `fut.result`). Rank 2 **deliberately** moves them inside so abandonment reclaims them and APScheduler can re-arm (wedge **#1087**). The impl Go must **not** “preserve” the current outside placement; the reversal is the fix. Moving the load inside does **not** reduce the work — it contains it. Occupancy **reduction** for the web tier is rank **1** (and later inner bounding). Rank 2/3/(e) wait on Patch D (Patch F SATISFIED).

**(b3) COMPOSED FAILURE MODE — NAMED NON-GOAL (v4 rewrite; E2).** Not an unnamed long tail. **Intentional replacement** (#1008 fixing #906’s skip-forever wedge) with an **incomplete model**: generation tokens bound **results**, not worker **lifetime or side effects**. Failure-mode framing only: **#906 re-opened, convoy-multiplied** by **#1009/#1021/#1022** — never “root cause.” The #906 failure mode (#1008 re-opened, #1009/#1021/#1022 amplified) is a code-level causal chain; the exact exhausted resource is UNPROVEN and requires runtime capture (Patch D). Cuts 1–4 / (e) contain the aftermath; they do not resolve the composed conflict. This plan measures and bounds. **Follow-up Go (separate)** completes “#1008’s goal, correctly” at the PR-composition level (fresh start **and** bounded previous worker). If the tail degrades (TMC latency, subnet-count creep toward cap 24, ambient web-tier contention), the episode recurs even with containment cuts shipped — accepting this Go knowingly.

Hour pick: separate job, untouched unless a later Go says so.

**(d) Persistence:** JSON + `fcntl` file-lock, **not SQLite** on the direct daily-pick path: `data/daily_picks.json` (`daily_pick_engine.py:28-49`, `158-181`), `data/pick_score_cache.json` (`pick_score_cache.py:40-46`, lock `101-108`, session `163-228`). Downstream `record_pick_prediction` / `record_hold_decision` were **not** traced as SQLite in this pass — no repo-wide “no SQLite” claim.

## 4. Ranked cuts (not a single pick)

| Rank | Option | What | Effort / risk | Hits tonight’s symptom? |
|------|--------|------|---------------|-------------------------|
| **1** | **(c)** GET single-flight + shed | One in-flight `_load`+lite enrich; extra hydrates get that result or last stored JSON. Borrow hour’s `_HOUR_PICK_LOCK` pattern **deliberately** (daily does not have it today). **Accepted interpretation (M4):** coalesce-single-flight — one shared `Future` on `_PICK_READ_EXECUTOR` (`_coalesce_daily_pick_flight`); extras join or shed to this flight’s stored JSON. Not a literal `_HOUR_PICK_LOCK` cached-or-busy. Do not re-litigate. Stop retry storms (G0 ×9). | Low. Shape unchanged. | **GET busy string + /health during burst** |
| **2** | Tick: move subnet+market load **inside** the 90s pool | **Reverses** current outside-future placement (`276-277`). Containment vs APScheduler / #1087 re-arm — **not** less work. | Low. 90s cap unchanged. | Tick occupancy vs APScheduler; not GET |
| **3** | **(b)** inner deadlines in `select_daily_pick` | Time-box TMC/council/proxy so the tick returns a real HOLD/LONG inside 90s instead of abandon. | Medium. Scoring behavior. | 00:17Z 90s HOLD (**containment**, not root latency — see b3) |
| **4** | **(e)** generation-counter hardening | Pre-persistence check in `get_or_create_today_pick`: bail before `_save` / HOLD records if `_work_generation` is no longer current. | Low-Med. Engine write path. | Post-timeout stale writes **(b1)** |
| — | **(a)** | GET scoring already off-path. Tick already background. Remainder = rank 2. Do not re-litigate P1. | — | — |
| — | **(d)** JSON `fcntl` | Not SQLite. Optional later: reduce lock/write cost. Skip for first impl. | Skip | No |

**(e)** closes the **(b1)** window. If scope is tight, defer **(e)** to its own Go with a one-line why — **do not silently drop it**; it is the only cut that targets the post-timeout write race.

**Recommended first impl PR (after review Go):** rank 1 only — GET single-flight + shed. That is **#1008’s GET-side analogue** (one in-flight hydrate; extras join or shed), not tick bounding. Later ranks (tick) implement “**#1008’s goal, completed correctly**”: fresh start **and** bounded previous worker — **not** restore #906.

Until runtime capture (§6 item 4, four falsifiable checks / Patch D) is complete, **rank 1 is the only mergeable cut** (items 1–2 passing). Patch F is SATISFIED with receipts. Ranks 2 / 3 / (e) wait on Patch D, not rank 1. No impl PR ships those ranks until that gate. Trimmed rank-1 code is PR **#1138** (M3/M4). Tick ranks are draft **#1140**, gated on Patch D — do not merge. **M5 (Joshua):** merge of #1138 to main *is* deploy.

Not #1112/#1113.

## 5. Constraints

- Response shape: stored LONG/HOLD (`published` / netuid / confidence) unchanged; timeout HOLD stays `status: timeout` + `_meta.stale` — never rewrite a scheduler HOLD into timeout.
- Hour pick untouched in the first impl PR (ok to **copy** its lock pattern onto daily GET).
- **90s stays. No deploy without Joshua. KILL=0.**
- #1112 / #1113 untouched. PR 1060 stays open fail-closed. #1058 stays closed (08-27 / #1071).
- **LINE-REF DRIFT:** this doc re-pins vs `5a33fe6c` (§8). Two older cites still exist in the thread (`pick_scheduler` 270-302 vs 265-297). An **implementation** Go must `git show` **then-current** HEAD and re-pin **all** line refs before citing either set. No plan section is authoritative on line numbers until that `git show`.
- **PATCH F — COMPOSED-LIFECYCLE REVIEW (precondition gate).** SATISFIED with receipts (the #1008 exact-diff item is now closed). PRs **#906, #1008, #1009, #1021, #1022** reviewed as **one** composed lifecycle at the static/diff layer (read-only; no code, no deploy). The conflict exists across those boundaries. Remaining later-rank gate is Patch D only.

  Spot-check receipts (2026-08-30) + git `show` of each SHA + regression-doc upgrade:

  | Claim | Status |
  |-------|--------|
  | #1022 TMC lock, peers block, serializes both endpoints | **Diff-verified** |
  | #1128 `if still_scheduled:` (run_once re-arms) | **Diff-verified** — not Aug-30 root without runtime evidence |
  | #906 overlap guard ADD `8f158de08` (`_work_thread` / `is_alive()` + skip log) | **verified** (2026-08-13T12:01:26Z) |
  | #1008 exact diff — verified (full SHA 1eb0a6bfa3 + test rename) | **verified** (2026-08-20T22:51:57Z): removes guard; adds `ThreadPoolExecutor(max_workers=1)`, generation bump, `fut.result(timeout=…)`, `shutdown(wait=False, cancel_futures=True)` |
  | #1008 VM-sizing `0769f631c8` (`shared-cpu-1x` → `shared-cpu-2x`) | **verified** (E1; current main `performance-1x` / `4gb`) |
  | #1008 merge `d3e331aad` ancestor of `5a33fe6c` | **verified** (2026-08-20T22:59:07Z). **MERGE ≠ DEPLOY** |
  | Side-effect gating (generation check AFTER `get_or_create_today_pick`) | **verified** in `1eb0a6bfa3`: gates returned payload only, not in-flight writes; `shutdown(wait=False)` cannot kill a running future |
  | #1009 forced retry | audit; verify PR body at impl time |
  | #1021 1712s wall / 128 CPU-s vs 90s | audit quote; re-verify PR body at impl time |

  Capture (Patch D) still proves *what* is exhausted. Patch F established the static chain: the fix must complete #1008’s incomplete replacement, not restore #906.

## 6. Validation (before any impl PR ships to prod)

No full G0 unless Joshua says so.

1. **GET occupancy:** `TestClient` + jammed `_DASHBOARD_EXECUTOR` (already `test_daily_pick_ignores_saturated_dashboard_executor`); add concurrent n=8 GET `/api/daily-pick` — one load, all 200, elapsed ≪ 0.5s × 8.
2. **Probe (local or one prod curl pair after deploy Go):** sequential GET `/api/daily-pick` duration_ms; `/health` p95 while n=10 parallel daily-pick. Compare to G0-1 p95 1245ms only as a *burst* check, not a close of PR 1060.
3. **Tick:** do not claim the 90s HOLD is fixed by rank 1. Rank 2/3/(e) get their own `duration_ms` on `last_tick` plus a **post-timeout side-effect audit** (no `_save` / HOLD records from an abandoned generation).
4. **RUNTIME CAPTURE — CONVOY HYPOTHESIS (falsifiable; primary).** Primary suspect: global TMC lock convoy (#1022) + generation overlap. Capture from the affected generation or the next recurrence **before any impl PR ships ranks 2/3/(e)**. Four checks (regression doc §4; A–E inventory demoted to fallback if these are ambiguous):
   1. Does a `daily-pick-work` generation **SURVIVE** the 90s timeout? (py-spy / faulthandler at timeout+5s and +60s)
   2. Does the 15-min retry create **ANOTHER** generation? (second executor, second nested scoring pool — `/jobs` + thread inventory at 00:15–00:17Z)
   3. Where are surviving `dpick-score` threads blocked? `_tmc_refresh_lock` / network reads / scoring GIL / score-cache `fcntl`
   4. Does thread count return to **baseline BEFORE** the retry?
   Deliverable: capture artifact naming the exhausted resource (TMC lock convoy / threads / GIL / network / volume). Patch F intersection (#1008 exact diff `1eb0a6bfa3` + #906 guard `8f158de08`) is **closed** at git-diff layer; runtime still needed to name the resource. Fallback grid if ambiguous: jobs / stacks / tick-active / fcntl holder / process metrics vs G0-1 `/health` p95 1245ms.
5. **ISOLATE MISFIRE GRACE:** `misfire_grace_time=180` (`internal/job_scheduler.py`; test asserts 180) can **absorb** catch-up backlog rather than fix occupancy. A validation run with backlog absorption **MUST NOT** be credited as occupancy improvement. State per run whether catch-up occurred; treat absorbed runs as **inconclusive**.
6. **#1128 CONTRACT SCRUTINY (diff-verified 2026-08-30):** `if reschedule and still_scheduled:` → `if still_scheduled:` in both Daily and Hour schedulers; `run_once(reschedule=False)` now re-arms when singleton (`test_daily_run_once_rearms_when_singleton`). Deliberate per commit message. Not Aug-30 root cause without runtime evidence. Track as a separate correctness item — an accidental `run_once` caller can now become a repeating scheduler.
7. **GATE:** no impl PR ships ranks 2/3/(e) until item 4 answers the exhausted-resource question (Patch D). Patch F (static composed-lifecycle) is SATISFIED with receipts. Until then **rank 1 is the only mergeable cut**, with items 1–2 passing.

## 7. Deliverable

This file + companions + MC log. Implementation = separate Joshua Go after review. Rank 1 only mergeable; Patch F SATISFIED; Patch D OPEN. No deploy without Joshua.

## 8. Source verification (re-pin vs `origin/main` `5a33fe6c`)

Verified on this checkout. `git diff --stat origin/main --` of these code files is empty (main is two docs-only commits on `docs/GITHUB_TOOLING.md` ahead of branch base `04614d46`).

| Claim | HEAD pin (`5a33fe6c` / this tree) | vs old `cfbe842a` cite | Status |
|-------|-----------------------------------|------------------------|--------|
| `PICK_READ_TIMEOUT` default 0.5s, 2-thread `pick-read` | `server.py:629-634` | `623-634` | **Confirmed.** Env override still needs prod evidence. |
| `_to_thread_timeout` = `wait_for` around executor | `server.py:661` | `661-672` | **Confirmed.** Await is bounded; worker may continue. |
| GET is read-only; busy payload | `api_daily_pick` `3122-3194`; hold `3096-3106` | `3121-3178` / `3096-3106` | **Confirmed.** Enrich timeout path `3179-3186` returns stored JSON, not busy. |
| Hour single-flight | `_HOUR_PICK_LOCK` `648`, `3253-3283` | `3240-3283` | **Confirmed.** Daily GET has no equivalent. |
| Tick: load **before** 90s future | `_tick` `270-375`; load `276-277`; future `284-302` | `265-297` | **Same code, new numbers.** `_tick` now starts at **270**. |
| Generation + abandon | `_work_generation` `215`; bump `280-282`, `297-298`; `shutdown(wait=False)` `302`; re-arm `346-375` | `212-215` / `312-369` | **Confirmed.** Comment at `213-214` still overclaims (“cannot commit results”) vs (b1) writes. |
| Engine writes | `get_or_create_today_pick` `184-327`; `_save` `241`/`284`; prediction/HOLD `286-325` | `184-225, 250-284, 286-325` | **Confirmed.** |
| JSON + `fcntl`, not SQLite | `daily_picks.json` `28-49`; cache `pick_score_cache.py:40-46`, `101-108` | same regions | **Confirmed** on this path. Prediction-loop not SQLite-traced. |
| Scoring / TMC / cache | `daily_pick.py:112`, `151-158`, `163-228`, `216-221` | `148-221` / `162-221` | **Confirmed** as `151-221` on HEAD. |
| Tests | homepage `36-92`; scheduler timeout-retry `350-393`; GET coarse guard `406-409`; dashboard-exec `test_api_handler_timeouts.py:836` | `350-390`, `398-404` | **Confirmed**; GET guard is `406-409` not `398-404`. |
| `misfire_grace_time=180` | default `internal/job_scheduler.py:32`; applied `98,119`; `tests/test_job_scheduler.py:31-38` | (v3 Patch D) | **Confirmed.** |

**Not a conflict:** older 265-297 vs HEAD 270-302 are the same `_tick` body at a later HEAD. Implementation Go re-pins again; do not paste `cfbe842a` numbers into code comments.
