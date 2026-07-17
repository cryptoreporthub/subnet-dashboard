# Living Brain Integration Audit

**Updated:** 2026-07-17  
**Baseline:** `main` post-#312 (`6c9b057`)  
**Question:** Is the learning loop ↔ mindmap ↔ soul map connected, correct, and optimized so the product actually learns and improves financial advice?

---

## Verdict (one sentence)

**The closed advice loop is real but narrow** — resolve → `nudge_expert` → `soul_map` weights → next pick — while most “memory” (dispositions, scenario outcomes, pick history, message-intel) is written and shown, but **does not steer the next financial call**.

---

## What works (closed loop)

```
live subnets (get_all_subnets)
  → effective_weights(soul_map) + signal_weights + impact_strength
  → score_subnet_for_hour/day → select_*_pick
  → record_pick_prediction → predictions.json + trail + scenario link
  → resolver_scheduler → grade
  → nudge_expert (+ trail weight_change)
  → next pick reads updated effective_weights
```

| Piece | Status |
|-------|--------|
| Expert weight learn on resolve | ✅ via `nudge_expert` (§27-4) |
| Regime tilt from graded history | ✅ `learned_regime_adjustment` in `effective_weights` |
| Signal weights nudged on resolve | ✅ persist; **silent** (no trail) |
| Trail + story path + time capsule | ✅ narrate the loop |
| Trust banner from gated stats | ✅ RF-2 primary surface |
| Living Focus / Public Self-Update | ✅ UI exists; **bugs below** |

---

## Architecture map

| Store | Written by | Reads for UI | Feeds next pick? |
|-------|------------|--------------|------------------|
| `data/soul_map.json` — `council_weights` | resolver, feedback, calibration, alignment, message-intel | learning APIs, Living Focus (intended) | **Yes** — `effective_weights` |
| `data/soul_map.json` — `signal_weights` | resolver | state_vector | **Yes** |
| `data/soul_map.json` — `learning_trail` | trail_bus / MindmapBridge | `/api/mindmap/trail` | No (display) |
| `data/soul_map.json` — dispositions | message_intel, pump | mindmap graph / cockpit | **No** |
| `data/predictions.json` | prediction_loop / resolver | story strip, portfolio, capsule | Indirect (grades → weights) |
| `data/scenario_memory.json` | create + resolve outcomes | APIs / letters | **Weak** — tags only; outcomes not in scorer |
| `data/pick_history.json` | resolver finalize | dashboard | **No** |

---

## Critical bugs (break “living brain” feel)

### LB-1 — Living Focus reads wrong calibration shape
- **Code:** `living_focus.js` expects `cal.calibration.expert_weights` or `cal.expert_weights`
- **API:** `get_calibration_status()` returns top-level **`weights`**
- **Effect:** “Who drives” / learn-strip weight display often empty `{}`

### LB-2 — Learn-strip netuid filter precedence bug
```js
if (!ev || ev.netuid != null && Number(ev.netuid) !== focusNetuid) return false;
```
- Events with `netuid == null` **pass** the filter → wrong “last learn” can show for Focus SN

### LB-3 — `?focus=` deep link unwired
- Subnet page CTA → `/?focus=N#section-living-focus`
- `living_focus.js` never reads query params

### LB-4 — Focus chips unscoped
- Scenario / postmortem chips use global APIs, not focus netuid

---

## High-impact gaps (memory that does not improve advice)

### LB-5 — Dispositions never enter scoring
Pump / message-intel / selector write `*_dispositions` into soul_map and trail, but `score_subnet_for_*` **ignores** them. Highest unused memory surface.

### LB-6 — Scenario outcomes stranded
`scenario_memory.record_outcome` grows the store; pick scoring uses prediction-regime hit rates only (`learned_regime_adjustment`), not scenario-store retrieval.

### LB-7 — Signal-weight learning invisible
`nudge_signal_weight` persists but emits **no trail** → Public Self-Update cannot show signal lean.

### LB-8 — Duplicate weight writers (fight `nudge_expert`)
| Path | Uses `nudge_expert`? |
|------|----------------------|
| Resolver `_nudge_weights` | Yes |
| `LearningEngine.record_feedback` | Yes |
| `alignment_nudge` | No — direct `save_weights` |
| `calibration.fire_weights` | No — intentional batch |
| `message_intel.self_learning.adjust_jury_weights` | No — **renormalizes sum→1.0** (fights multiplicative council scale) |

### LB-9 — Feedback path silent
`POST /api/feedback` nudges without trail emit → mindmap/Living Focus miss the event.

### LB-10 — Stub brain recommendations
`MindmapBridge.get_brain_recommendations` can fall back to hardcoded SN1/2/3 — competes with real pick engine if UI ever surfaces it.

---

## Medium gaps (coherence / trust)

| ID | Issue |
|----|-------|
| LB-11 | Homepage double-fetches `/api/daily-pick`, `/api/mindmap/trail`, `/api/simivision` (cockpit + Living Focus) |
| LB-12 | Story strip / mindmap graph / weekly letter ignore Living Focus netuid |
| LB-13 | Dual paper portfolios (council vs judges) confuse “did advice make money?” |
| LB-14 | Cockpit KPI can fall back to ungated `stats.accuracy` (RF-2 leak) |
| LB-15 | `/api/mindmap/summary` stub conviction ~50; unused on home |
| LB-16 | Picks use `get_all_subnets()`, judges use `merged_data` — feed divergence |
| LB-17 | Pick history never influences scoring |

---

## Optimization target (living brain done-right)

**One Focus object · one memory write path · one weight path · one advice read path.**

1. **Single weight authority:** all online nudges → `nudge_expert` (+ trail); calibration remains batch; kill or quarantine message-intel renormalize.
2. **Memory → score:** dispositions + scenario outcomes as soft features in `state_vector` / `effective_weights` (capped, honest-empty when cold).
3. **Trail complete:** signal-weight + feedback nudges emit `weight_change`.
4. **UI one brain:** Living Focus owns focus netuid; trail/chips/story/learn all filter by it; fix LB-1–4.
5. **RF-2:** no accuracy outside `trust_banner`.
6. **One subnet feed** for picks + judges when chain live.

---

## Recommended automation (§30 — Living Brain closure)

See `post-s30-living-brain-plan.md`. Human items remain out of scope.

Priority order:
1. Fix LB-1–4 (UI correctness) — ship first
2. LB-7–9 (trail completeness + feedback trail)
3. LB-8 message-intel weight quarantine
4. LB-5–6 (memory → score) — careful, needs tests
5. LB-11–16 polish

---

## What not to do

- Redis / second foundation
- Fake accuracy theater
- Full graph rebuild before Focus filter works
- Letting message-intel renormalize fight council weights without a gate
