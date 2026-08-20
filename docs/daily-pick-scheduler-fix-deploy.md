# Daily pick scheduler fix — prod deploy & watch

**PR:** #1008 (`cursor/stage2-representative-soak-ebef`, commit `1eb0a6bf`)  
**Scope:** Production correctness fix only. Does **not** advance Stage 2/3 or v2 cutover.

## What ships

1. **Orphan-thread fix** — daily pick timeout mirrors resolver: `ThreadPoolExecutor` + generation-token abandonment. Retries no longer block on `_work_thread.is_alive()`.
2. **Conviction-row cache** — `_conviction_rows()` loaded once per `select_daily_pick` pass (24× → 1× 3000-row JOIN).

## Accepted tradeoff (not a bug if you see this)

Python cannot kill abandoned threads. On timeout, the scheduler **logically** abandons work (`worker abandoned`) and the **next tick starts fresh**, but the old thread may still run to completion in the background and contend for GIL/CPU until it finishes.

**Post-fix expectation:** with the conviction-row cache, ticks should rarely hit 90s. Orphan contention should become **rare**, not routine. If timeouts still happen every cycle after deploy, the correctness fix is working only if `last_run_at` keeps advancing — but you likely still have a performance/capacity follow-up.

---

## Pre-merge / pre-deploy: isolate this from Stage 2/3

PR #1008 also carries Stage 2b scaffolding (representative soak toml, scripts, GHA workflow). **None of that runs because you merged.** Verify before merge + before triggering deploy:

| Check | Expected |
|-------|----------|
| **Auto-deploy on merge?** | **No.** `.github/workflows/fly.yml` is `workflow_dispatch` only (push-to-main disabled since 2026-08-19 incident). Merging lands code in git; prod changes only when someone manually runs **Fly Deploy**. |
| **Stage 2 soak workflow** | **Manual only.** `.github/workflows/fly-stage2-representative-soak.yml` requires `workflow_dispatch` + `confirm=soak-representative`. Will not fire on merge. |
| **Deploy config used** | **`fly.toml` only** (`flyctl deploy --config fly.toml`). Does **not** deploy `fly.worker-v2-essential-soak.toml`. |
| **Process topology after deploy** | Workflow enforces **v1 inline**: `web=1`, `worker=0`, clears `WORKER_SPLIT_V2` / `WORKER_INTERNAL_URL` secrets. |
| **Scripts that must NOT be run tonight** | `scripts/fly_stage2_representative_worker.sh`, `fly_stage2_representative_rollback.sh`, Stage 3 cutover scripts. |
| **Co-shipped but passive (OK on v1 deploy)** | Pick scheduler fix + conviction-row cache (the reason to ship). `internal/tmp_boot_reaper.py` boot hook (volume `.tmp` cleanup — runs once at boot, unrelated to soak). `fly.toml` `shared-cpu-2x` (already applied manually; deploy reaffirms). Stage 2 scripts/toml sit in repo **dormant**. |

**Deploy action tonight = one manual Fly Deploy workflow run.** That ships the scheduler fix to v1 prod. It does **not** start representative soak or Stage 3 cutover.

---

## Deploy steps

1. Merge PR #1008 to `main`.
2. Manually trigger **Fly Deploy** workflow (GitHub Actions → Fly Deploy → Run workflow). Do **not** trigger Fly Stage 2 representative soak.
3. Confirm deploy completes (`flyctl releases list -a subnet-dashboard` or workflow green).
4. **Do not** run Stage 2 representative soak or Stage 3 cutover scripts.
5. Start the watch window below **before** declaring success.

---

## Watch window — minimum 30–45 minutes (2–3 retry cycles)

A single `last_run_at` bump after deploy is **necessary but not sufficient**. Prior incidents tonight (soak #4 clean probes, Stage 3 gate 8/8 before hold failure) all looked fine on the first data point.

| Requirement | Detail |
|-------------|--------|
| **Duration** | ≥ **30–45 min** (covers **2–3** full retry cycles at `DAILY_PICK_RETRY_MINUTES=15`) |
| **Poll interval** | Every **5 min** (or use the script below every 15 min) |
| **Primary signal** | `pick_scheduler.daily.last_run_at` **advances** on each observed cycle |
| **Secondary signal** | `last_run_error` is **explicit text**, not silence / frozen state |

### Poll command (save output with timestamps)

```bash
export APP_BASE_URL="${APP_BASE_URL:-https://subnet-dashboard.fly.dev}"

curl -fsS --max-time 30 "$APP_BASE_URL/api/learning/health" | python3 -c "
import json, sys
from datetime import datetime, timezone

d = json.load(sys.stdin)
pick = d.get('pick_scheduler') or {}
daily = pick.get('daily') or {}
last_tick = pick.get('last_tick') or {}
dp = d.get('daily_pick') or {}

now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
print(f'=== {now} ===')
print('learning-health status:', d.get('status'))
print('daily.last_run_at:     ', daily.get('last_run_at'))
print('daily.last_run_ok:     ', daily.get('last_run_ok'))
print('daily.last_run_error:  ', repr(daily.get('last_run_error')))
print('last_tick.ok:          ', last_tick.get('ok'))
print('last_tick.error:       ', repr(last_tick.get('error')))
print('last_tick.run_at:      ', last_tick.get('run_at'))
print('daily_pick.action:     ', dp.get('action'))
print('daily_pick.scheduler_hold:', dp.get('scheduler_hold'))
print('daily_pick.reason:     ', repr(dp.get('reason')))
"
```

Run every 5 minutes for **at least 45 minutes**. Keep the log — you need to see **multiple** advances, not one.

---

## What “working” looks like vs the old bug

### Correctness fix is working

- `last_run_at` **increments** across 2–3 cycles (timestamps ~15 min apart when pick not ready).
- `last_run_error` / `last_tick.error` shows **readable errors each cycle**, e.g.:
  - `"daily pick tick timed out after 90s"` (timeout path — OK for *correctness* if timestamp keeps moving)
  - `"daily pick scheduler failed"` / hold reason in `daily_pick.reason` (scheduler_hold path)
  - `null` / absent error with `last_run_ok: true` (clean success)
- Fly logs show **`worker abandoned`** on timeout (not `worker left running`).
- You do **not** see `"daily pick tick skipped; previous worker still running"` (removed).

### Old bug still present (do not declare success)

- `last_run_at` **frozen** for 20+ min while retries should have fired.
- `last_run_error` stuck on an old value with **no new `last_tick` entries**.
- Silence: scheduler appears idle with no advancing timestamps and no new log lines.
- `"previous worker still running"` skip messages (pre-fix code still running — wrong release).

---

## Separate bar: v1 freshness gate (Stage 2/3 unblock)

After the 30–45 min watch, if correctness looks good:

```bash
./scripts/fly_v1_freshness_gate.sh
```

**Note:** the gate **fails** while `last_run_error` still contains `"timed out"` — even if `last_run_at` is advancing correctly. That is intentional strictness for Stage 2/3:

| Observation | Meaning |
|-------------|---------|
| `last_run_at` advancing + timeout errors each cycle | Correctness fix working; pick still slow or overloaded |
| Gate exit 0 | At least one **clean** successful tick (no timeout in last error) — required before soak/cutover |
| Gate exit 1 + advancing timestamps | Ship was worth it; keep Stage 2/3 blocked until a clean success tick |

---

## Performance hypothesis to validate during watch

**Question:** Did the conviction-row cache mostly eliminate the 90s trigger, or are timeouts still routine?

| Outcome | Interpretation |
|---------|----------------|
| Ticks complete in seconds; `last_run_ok: true`; no timeout errors | Performance fix likely removed the trigger; orphan tradeoff rarely matters |
| `last_run_at` advances but most cycles still timeout at 90s | Correctness fix working; investigate remaining slow path (subnet load, resolver GIL, other schedulers) |
| Frozen `last_run_at` | Correctness fix not deployed or another wedge — investigate before anything else |

Check Fly logs during the watch:

```bash
flyctl logs -a subnet-dashboard --no-tail | rg "daily pick tick|pick scheduler|worker abandoned" | tail -30
```

Count timeout lines over 45 min. **Zero or one** → cache likely solved the trigger. **Every 15 min** → correctness fixed, performance still needs work.

---

## Log signatures (post-fix)

| Event | Expected log |
|-------|----------------|
| Timeout | `daily pick tick timed out after 90s (worker abandoned)` |
| Success | No timeout warning; `last_run_ok: true` in health |
| Removed (old) | `worker left running`, `previous worker still running` |

---

## Stage 2 / Stage 3

**Remain blocked** until:

1. This watch shows **2–3 advancing** `last_run_at` cycles (30–45 min), **and**
2. `./scripts/fly_v1_freshness_gate.sh` exits 0 (clean success tick, not just advancing timeouts).

Do not run `fly_stage2_representative_worker.sh`, Stage 3 cutover, or lock worker VM sizing based on this deploy alone.

---

## Rollback

If `last_run_at` freezes again or daily-pick degradation worsens:

```bash
flyctl releases list -a subnet-dashboard
flyctl releases rollback -a subnet-dashboard   # pick previous release
```

Re-run the 45 min watch after rollback to confirm state.

---

## Quick checklist

- [ ] **Deploy isolation confirmed:** merge ≠ deploy; Fly Deploy uses `fly.toml` only; no Stage 2/3 scripts/workflows triggered
- [ ] PR #1008 merged; **Fly Deploy** workflow manually triggered and green
- [ ] Poll learning-health every 5 min for **≥ 45 min**
- [ ] Confirm `last_run_at` advanced **≥ 2 times**
- [ ] Confirm errors are explicit (timeout/hold/success), not silence
- [ ] Note timeout frequency (rare vs every cycle) — separates correctness fixed vs problem solved
- [ ] Confirm logs say `worker abandoned`, not `worker left running`
- [ ] Run `./scripts/fly_v1_freshness_gate.sh` only after watch log saved **and** both bars met (advancing timestamps + timeouts rare)
- [ ] Stage 2/3 stay blocked until gate green
