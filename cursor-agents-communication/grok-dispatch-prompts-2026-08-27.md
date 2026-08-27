# Grok dispatch prompts — 2026-08-27

**main:** `688f0aef`  
**Models:** Grok 4.6 **medium** (slow + medium first; escalate high only if stuck) · read-only LOCK output · Composer implements · Luna final pass on hydration/contract  
**Board:** `cursor-agents-communication/board.md`

Run **Grok A** and **Grok B** in parallel. Do not edit product code in these runs.

---

## Grok A — #1058 Phase 2 hydrate stagger LOCK

```
You are a read-only Grok 4.6 medium design agent on cryptoreporthub/subnet-dashboard.

TASK: Produce a structured LOCK for Phase 2 of issue #1058 — client-side hydrate stagger in static/js/cockpit_hydrate.js. Composer will implement from your LOCK; Luna reviews AC/honesty after.

READ FIRST (in order):
1. artifacts/g0-baseline/G0_REPORT.md
2. artifacts/g0-baseline/POST_P1_AUDIT.md
3. artifacts/g0-baseline/POST_P1_REPROBE.md
4. cursor-agents-communication/g0-1058-composer-p1-handoff.md
5. static/js/cockpit_hydrate.js (run(), bootstrapCouncilHeroHydrate(), kickPriorityPanels(), fetchJsonRetry, SSE start)
6. harness/g0_hydration_starvation/run_g0.py (HERO_COMPLETE definition, 10s budget)

CONTEXT (do not re-litigate):
- P1 merged on main (#1058 / 64176d16): homepage SSR pick read-only; GET /api/daily-pick bounded off executor saturation.
- Post-P1 prod still FAILS close: hero >10s or NEVER; /api/learning/stats first fetch aborted at 28s; /health p95 ~8s during 27–28 concurrent /api/* burst.
- Root cause: shared-cpu web+inline-worker event-loop occupancy from hydration fan-out at DCL (~2–5s), not sequential daily-pick scoring alone.
- Phase 2 is JS stagger only. Forbidden in your LOCK: fly.toml*, Dockerfile, resolver.py, grading modules, select_daily_pick scoring changes, worker_proxy.

DELIVERABLE — structured LOCK:
VERDICT: PASS | CONDITIONAL | FAIL
DECISIONS: (5–10 bullets) — tiered fetch order, max concurrent hydrates, SSE deferral, retry/abort policy for stats+daily-pick, what stays on HomeHydrateCache
FILES: exact paths + functions to touch (expect cockpit_hydrate.js; note if living_focus.js / home_live_refresh.js must coordinate)
AC: measurable — hero complete ≤10s AND /health p95 <500ms during burst on two prod G0 runs; stats must parse in budget; timeout HOLD must stay stale-shaped
PHASES: slice 2a (minimal hero path) vs 2b (defer non-hero) if needed
RISKS / NON-GOALS: list what this will NOT fix (infra, hollow mindmap-summary, resolver watchdog)
ESCALATE_HIGH?: no | yes (why)
TEST PLAN: how Composer proves without only sequential curl

Save conclusions to Ditto (source: cursor-agents-communication) and reference LOCK_PATH in STATUS.
```

---

## Grok B — REV3 Site A watchdog `dd13cfb298` root-cause LOCK

**Status:** ✅ **DONE** — Sentinel PASS 2026-08-27 (no new Composer slice)

**Verdict summary:** Audit at 05:12Z ran on `35b1bf34` (75 min before #1055 `b586afc`). `dd13cfb298` is an unresolvable HOLD counterfactual shadow; #1055 already fixes scope-leak. Close = owner deploy SHA ≥ `b586afc` + 1 `resolve_due` tick. Live watchdog already clean at 06:06Z (`oldest` ≠ `dd13cfb298`).

---
You are a read-only Grok 4.6 medium root-cause agent on cryptoreporthub/subnet-dashboard.

TASK: Explain why REV3 Site A remains OPEN for watchdog row dd13cfb298 after #1055 shadow expire merged. Output verdict + smallest fix slice (code vs ops vs wait-for-tick).

READ FIRST (in order):
1. Ditto search: "REV3 Site A dd13cfb298" / "subnet-dashboard REV3 closeout"
2. tests/test_shadow_resolver_expire.py
3. scripts/rev3_prod_audit.sh
4. internal/council/resolver.py and resolver scheduler paths that touch shadow/counterfactual rows
5. PR #1055 diff intent: expire shadow rows past grace; exclude from council watchdog pending count
6. .github/workflows/ (REV3 closeout audit workflow from #1053/#1054)

KNOWN STATUS (2026-08-26 Ditto):
- deploy_sha=35b1bf34; Test1 PASS tick≥2×; Site C PASS.
- Site A OPEN: row dd13cfb298 shadow pending + price_data_unavailable unchanged T0→T1 after ticks.
- Site B NOT CLOSED: cadence/honest running OK; watchdog still open.
- GRADING_MODE=legacy; split-v2 blocked.

QUESTIONS TO ANSWER:
1. Is dd13cfb298 legitimately unresolvable (missing price) vs a grace/expire bug vs scope-leak (watchdog counting rows #1055 should exclude)?
2. Does dry_run recover change anything on prod volume, or is this data-only?
3. What is the smallest Composer slice (if any) with AC + test, vs human ops (volume edit / wait / manual resolve)?

DELIVERABLE — structured LOCK:
VERDICT: PASS (explainable + no code) | CONDITIONAL (small fix) | FAIL (needs deeper redesign)
DECISIONS: (3–7 bullets)
FILES: only if code fix recommended
AC: Site A close criteria — row state after N ticks; watchdog pending_count behavior
RISKS: do not recommend fly deploy, fly.toml, or split-v2 without human approve
ESCALATE_HIGH?: no | yes (why)

Save to Ditto (source: cursor-agents-communication). Tag related subject: Subnet Dashboard REV3.
```

---

## After both LOCKs land

| Step | Owner | Action |
|------|-------|--------|
| 1 | Composer | Implement Grok A Phase 2 stagger on `cursor/hydrate-stagger-phase2-f603` |
| 2 | Luna | Final pass on #1058 AC (hero ≤10s, /health p95, honest stale HOLD) |
| 3 | Composer | If Grok B recommends code fix, separate small PR; else document ops closeout |
| 4 | Any agent | Refresh `board.md` STATUS; Ditto `save_memory` with main=<sha> |

**Queue behind A/B:** Phase L3/L4 WebSocket+rules LOCK · Intel #1034 merge honesty review · accuracy-lift interpretation (gated).
