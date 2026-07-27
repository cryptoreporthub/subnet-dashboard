# Unified LOCK — Confidence · Calibration · Living Brain · Graph-lite · Council LONG

**Status:** LOCK (plan) — promote from Ditto review optional; Cursor may execute Wave 1 immediately  
**Updated:** 2026-07-27  
**Baseline:** `main` @ `8406a17` (#541)  
**Supersedes:** stale #491 / #487 as sole specs (reconcile into this lock)  
**Canon:** `living-brain-audit.md` · `post-s30-living-brain-plan.md` · `confidence_calibration.py`

---

## North star

One closed loop: **memory writes → graph shows them → scoring reads them (soft, capped) → confidence decides publish → council LONG when gate clears → resolver grades → weights nudge → repeat.**

No fake accuracy. No second weight path. No full D7 money-flow graph (deferred).

---

## Current state (honest)

| Track | On `main`? | Open PR | Gap |
|-------|------------|---------|-----|
| **Confidence** | ✅ `confidence_calibration.py`, blended prior, score boost | #491 (likely redundant) | Close #491 after diff vs main |
| **Calibration** | ✅ `publish_gate` 40%, red-team cap tests | — | Prod soak + tune from graded data |
| **Living Brain §30** | ✅ slices 1–10 | — | LB-9 feedback trail, LB-12 focus-scoped graph |
| **Graph-lite** | ⚠️ `/api/mindmap/graph` exists (trail + dispositions) | — | No focus filter, weak scenario/weight edges |
| **Council LONG** | ⚠️ engine wired; often HOLD | #487 | Hydrate stability + gate experiment docs |

---

## Execution waves

```text
Wave 1  Confidence + Calibration + Council LONG  (one PR train)
  → Wave 2  Graph-lite backend (edges + focus API)
    → Wave 3  Graph-lite UI + Living Focus sync
      → Wave 4  Prod tune + close stale PRs
```

**Hard rule:** Wave 2 does not change publish math. Wave 1 does not redesign graph UI.

---

## Wave 1 — Confidence · Calibration · Council LONG

**Branch:** `cursor/wave1-council-long-calibration-1d2f`  
**Goal:** Healthy picks clear 40% gate; day hero can show LONG when deserved; red-team notes not kill shots.

### W1-1 Reconcile open PRs
- [ ] Diff `origin/main` vs #491 and #487; cherry-pick only deltas not on main
- [ ] Close #491 if empty; merge #487 if hydrate/gate docs remain
- [ ] Single changelog in PR body

### W1-2 Confidence path (verify, don’t rewrite)
- [ ] `blended_prior` + `score_boost` + `reliability_factor` used in `_compute_confidence`
- [ ] `red_team.audit_daily_pick` max compound haircut ≤12%
- [ ] Replay: SN58/SN36-style fixtures clear gate in `test_publish_gate_red_team.py`

### W1-3 Council LONG publish
- [ ] `daily_pick_engine` uses `publish_gate_fraction()` (default 0.40)
- [ ] Cockpit + hero copy: HOLD vs LONG honest (`audited` flag on picks snapshot)
- [ ] `DAILY_PICK_PUBLISH_GATE` env documented; no sub-40 experiment until 2w prod at 40%

### W1-4 Prod soak (scripted)
- [ ] `./scripts/check_learning_loop.sh` green
- [ ] `curl /api/daily-pick` → `action` long when `final_confidence >= 0.40`
- [ ] Log 7d: publish rate, red-team binding rate, graded hit rate

**AC:** pytest `test_confidence_publish_gate` `test_publish_gate_red_team` `test_council_basic` green; contract unchanged.

---

## Wave 2 — Graph-lite backend

**Branch:** `cursor/wave2-graph-lite-backend-1d2f`  
**Goal:** Graph reflects living memory; API supports focus scoping.

### GL-1 Focus-scoped graph
- [ ] `GET /api/mindmap/graph?focus=<netuid>` filters nodes/edges to ego-net (1-hop)
- [ ] Empty → honest `{ nodes: [], edges: [], empty: true }`

### GL-2 Scenario edges
- [ ] Read `scenario_memory` outcomes; edge `subnet → scenario` with `kind: scenario_outcome`
- [ ] Weight from outcome correctness (capped)

### GL-3 Weight-change edges
- [ ] Trail `weight_change` events → edge `judge/expert → subnet`
- [ ] Dedupe by `(expert, netuid, day)`

### GL-4 Disposition → score (read path only)
- [ ] Graph shows disposition node linked to subnet (exists); document that §30-6 already feeds scorer
- [ ] API `summaries.learning` includes disposition count for focus SN

**Files:** `internal/mindmap/graph.py`, `internal/learning/routes.py`, `tests/test_phase_g_mindmap_graph.py`

**AC:** focus filter test; scenario edge fixture test; contract `/api/mindmap/graph` 200.

---

## Wave 3 — Graph-lite UI + Living Brain polish

**Branch:** `cursor/wave3-graph-lite-ui-1d2f`

### GL-5 Living Focus handoff
- [ ] Tap subnet chip → `/?focus=N` loads graph panel filtered (reuse GL-1)
- [ ] Story strip / weekly letter respect `focus` query (LB-12)

### GL-6 Interactive mindmap panel
- [ ] `mindmap_graph.html` + JS: render nodes by kind (color legend)
- [ ] Quiet state when `empty: true` — no spinner >5s

### LB-9 Feedback trail
- [ ] `POST /api/feedback` emits `weight_change` or `disposition_shift` via trail_bus

**AC:** G0 manual: focus SN → graph shows ≥1 edge or honest quiet; feedback POST creates trail row.

---

## Wave 4 — Prod tune & housekeeping

- [ ] 14d dashboard: LONG publish %, hit rate, red-team frequency
- [ ] Gate tune proposal (stay 40% or 38%) — human sign-off only
- [ ] Close superseded PRs: #491, #487, #455, #449 (per STATUS)
- [ ] Update `board.md` Active → Done

---

## Explicit non-goals

- Full money-flow graph (D7)
- Redis / second server
- Sub-40% gate without prod review
- Message-intel renormalize weights
- Telegram / Discord ingest (human ops)

---

## Ditto handoff

```
LOCK_PATH: cursor-agents-communication/brain-calibration-unified-lock.md
STATUS: promoted
WAVE: 1 ready
```
