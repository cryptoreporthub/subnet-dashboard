# Hydrate desk investigation — serial babysit plan

**Created:** 2026-08-03  
**main at plan:** `52e129d`  
**Cadence:** investigate → root-cause LOCK → one PR → merge → `./scripts/babysit_phase.sh sprint` + problem-specific live checks → Ditto STATUS → **only then** next problem.  
**Pipeline:** Grok LOCK → Composer build → Sonnet low on diff.  
**Ownership:** P1–P2 = Agent A (`internal/learning/*`, council/daily-pick); P3 = conflict-surface ok (`/api/judges` + timeout wrappers). Do not touch Agent B modules unless a proven shared root cause forces it.

**North star:** Homepage hydrate empties are mostly *honest product state*, not CSS. Fix the three live soft-failures so the desk either shows a real call or an honest, stable reason — never a silent/pending lie or busy wedge.

---

## Rules (hard)

1. **Serial only.** Do not start P2 while P1 is open. Do not start P3 while P2 is open.
2. **Resolved means live.** Local green is not enough — Fly Deploy success + babysit + problem AC on `https://subnet-dashboard.fly.dev`.
3. **One root cause per PR.** If investigation finds two bugs, fix the primary; park the other as a follow-up note inside this plan (do not jump ahead).
4. **No trust-gate cheat.** Do not lower `min_graded` from 30 to “make proof look live.” P2 may fix *why graded stays at 1*, not the product threshold.
5. **No blind-merge of stale drafts** (#686/#675/#692/#650).

### Babysit after every merge

```bash
BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh sprint
APP_BASE_URL=https://subnet-dashboard.fly.dev ./scripts/check_learning_loop.sh
# plus the problem-specific curl checks in each section below
```

Abort next problem if babysit EXIT ≠ 0 (unless WARN-only documented soak noise).

---

## Baseline (2026-08-02 live snapshot — re-probe at each start)

| Probe | Observed |
|-------|----------|
| `/health` | OK |
| `/api/daily-pick` | `status=pending`, `action=HOLD`, `reason="today's pick forming"`, `pick=null` |
| `/api/daily-pick/weighed` | `shortlist=[]` |
| `/api/learning/stats` trust_banner | `ready=false`, `graded=1`, `min_graded=30`, message `Not enough graded picks yet (1/30)` |
| `/api/learning/health` | resolver running, `pending≈6`, oldest ~1h |
| `/api/judges` | `error='busy'` (soft) |
| `/api/top-pick/hour` | `status='timeout'` (still may return picks) |
| Most other hydrate GETs | 200 |

Homepage quiet copy matched trust gate: `Not enough graded picks yet (1/30)`.

---

## P1 — Daily pick stuck pending / HOLD

**Symptom:** Hero daily call never publishes; hydrate shows forming/HOLD with null pick.

### Investigation checklist (must complete before coding)

- [ ] Trace `/api/daily-pick` handler → store read → publish/formation writers
- [ ] Identify who sets `reason="today's pick forming"` and `status=pending`
- [ ] Check Fly volume state vs code paths: snapshot file, rotation hour, gates (conviction, red-team, LONG unlock)
- [ ] Compare `/api/learning/health.daily_pick` vs `/api/daily-pick` for skew
- [ ] Check scheduler / inline worker: is daily formation invoked? last success? errors in logs if available
- [ ] Reproduce locally with fixture that should publish vs should HOLD honestly
- [ ] Decide: **bug** (should have published) vs **honest HOLD** (gates correctly blocked) — if honest, fix UX copy/status so UI isn’t “forming forever”

### Done when (AC)

- [ ] Root cause written in a short LOCK under `/opt/cursor/artifacts/plans/` (or this file’s P1 log)
- [ ] PR merged fixing the root cause (or documenting intentional HOLD + clearer API/UI reason if no code bug)
- [ ] Live `/api/daily-pick` is **not** indefinitely `pending` + empty reason loop:
  - either `pick` present with `action` BUY/SELL/LONG/SHORT (product verbs as implemented), **or**
  - stable honest HOLD with a **specific** gate reason (not eternal “forming”)
- [ ] `/api/daily-pick/weighed` consistent with that decision (empty shortlist OK only if HOLD/no pick)
- [ ] Babysit sprint + `check_learning_loop.sh` green/WARN-only
- [ ] Ditto STATUS: `P1 DONE main=<sha>`

### P1 log

| Date | Finding | PR | Live verify |
|------|---------|----|-----------|
| 2026-08-03 | Root cause: DailyPickScheduler always rescheduled to next UTC 00:15 after any tick — one failed/hung cold-start left the desk on eternal `pending`/`today's pick forming`. GET stays read-only (correct). Fix: retry every `DAILY_PICK_RETRY_MINUTES` until today exists; tick timeout; expose `pick_scheduler` on learning/health. | #781 | Partial — retry live but tick wedges VM; still forming |
| 2026-08-03 | P1b: on tick timeout/fail write `scheduler_hold` HOLD (specific reason); keep retrying; persist `data/pick_scheduler_state.json` for web health | #782 | Live HOLD with reason (revealed datetime bug) |
| 2026-08-03 | P1c: `state_vector.attach_council_prediction` used `_dt.timezone.utc` but `_dt` is `datetime` class — AttributeError aborted every tick | #783 | Live HOLD: Confidence 34% below 40% audit gate; scheduler last_ok=true |

---

## P2 — Graded sample stuck at 1/30 (trust gate)

**Symptom:** Proof band / trust banner stay building at `1/30` despite resolver “running” and pending predictions.

**Gate:** Start only after P1 DONE.

### Investigation checklist

- [ ] Trace graded counter: `internal/learning/trust_stats.py` + `/api/learning/stats` + predictions store
- [ ] Why `graded=1` while watchdog `pending_count≈6`? Are pendings never becoming graded?
- [ ] Resolver tick: due times, price fetch failures, expiry path, duplicate path
- [ ] Confirm ledger vs `predictions.json` on Fly volume (not local dirty tree)
- [ ] Check whether resolves write stats but trust_banner reads a different store
- [ ] Historical: did volume wipe / epoch reset zero the graded corpus?

### Done when (AC)

- [ ] Root cause LOCK written
- [ ] PR merged (resolver/store/stats path) — **without** lowering `min_graded`
- [ ] Live evidence that pending→graded progresses (graded increases over resolver ticks, or pending ages clear with graded outcomes)
- [ ] If sample is legitimately tiny post-wipe: document recovery path + ETA; ensure UI message stays accurate
- [ ] Babysit + learning-loop check
- [ ] Ditto STATUS: `P2 DONE main=<sha>`

### P2 log

| Date | Finding | PR | Live verify |
|------|---------|----|-----------|
| | | | |

---

## P3 — `/api/judges` returns busy

**Symptom:** Hydrate judges panel soft-fails with `error='busy'`.

**Gate:** Start only after P2 DONE.

### Investigation checklist

- [ ] Find busy/load-shed/timeout path for `/api/judges`
- [ ] Measure live latency under idle vs concurrent homepage hydrate
- [ ] Check GIL / sync work on request path (py-spy pattern from #709/#710)
- [ ] Decide: cache stale-while-revalidate, shorter critical path, or explicit degraded payload (not opaque busy)

### Done when (AC)

- [ ] Root cause LOCK written
- [ ] PR merged
- [ ] Live: 3 consecutive `/api/judges` within timeout return usable payload (or explicit structured degrade without `busy` wedge)
- [ ] Homepage hydrate no longer marks judges section failed solely due to busy
- [ ] Babysit sprint green/WARN-only
- [ ] Ditto STATUS: `P3 DONE main=<sha>` — plan CLOSED

### P3 log

| Date | Finding | PR | Live verify |
|------|---------|----|-----------|
| | | | |

---

## Out of scope (do not expand)

- Frontend redesign / CSS / thumb dock
- Lowering trust `min_graded` for cosmetics
- Re-enabling worker split v2
- Accuracy-lift experiments (gated Aug 4 H2)
- Blind merges of stale drafts

---

## Status snapshot

| Problem | Status |
|---------|--------|
| Plan committed | DONE — #780 (or branch) |
| P1 daily-pick pending | **DONE** main=3c47a3f (#781–#783) |
| P2 graded 1/30 | IN PROGRESS |
| P3 judges busy | BLOCKED on P2 |
