# STATUS

**Updated:** 2026-07-27T02:15:00Z  
**main:** `9e7b4ee` (#530 learning-loop audit) · **in flight:** `cursor/score-snapshot-babysit-4988`  
**active plan:** Learning loop babysit → §30 docs closure

---

## Shipped recently

| PR | What |
|----|------|
| #527 | Learning health snapshot meta + §30-9 trail dedupe |
| #528 | Pump whale alerts |
| #529 | §30-2 focus chips + §30-8 RF-2 KPI honesty |
| #530 | Learning loop audit: heavy_job_gate, health executor, plan doc fix |

---

## Prod babysit (2026-07-27)

- Intermittent `/api/learning/health` timeouts when VM wedged — re-run after deploy
- Core loop when healthy: `status=ok`, worker alive, resolver running, HOLD daily
- **Open:** `score_snapshots.json` not on volume — L1 babysit branch addresses scheduler + cross-process health

**After every merge:**

```bash
./scripts/check_learning_loop.sh
APP_BASE_URL=https://subnet-dashboard.fly.dev ./scripts/verify_prod.sh
```

---

## §30 queue (synced)

| Slice | Status |
|-------|--------|
| §30-1–3, §30-6–10 | ✅ main |
| §30-2, §30-8 | ✅ #529 |
| §30-4/5 | ✅ code + tests (self_learning nudge, alignment_nudge) |
| §30-0 docs | in babysit PR |

---

## Human only

1. Close superseded PRs: #455, #491, #487, #474, #449
2. G0 human 390px sign-off
3. Telegram session bootstrap if `check_telegram_ready.sh` not OK
4. **Never** `WORKER_HEAVY=full` on single 2GB Fly VM
