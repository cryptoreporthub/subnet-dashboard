# §30 — Living Brain closure (automated)

**Status:** READY  
**Updated:** 2026-07-17  
**Baseline:** post-#312 · audit `living-brain-audit.md`  
**Goal:** Connect mindmap + soul map + learning loop so memory actually improves the next financial call — not just narrate it.

**Human items:** still excluded (F7, Telegram, Discord, email).

## Agent prompt

```
§30 LIVING BRAIN:
- Read living-brain-audit.md → this file → active slice AC only.
- One slice per turn. Branch: cursor/s30-<slug>-c3fd off latest main.
- Ready PR · merge when CI green · auto-continue.
- No data/*.json · RF-2 · nudge_expert is online weight authority.
```

## Queue

| # | Slice | Fixes | State |
|---|-------|-------|-------|
| **§30-0** | Docs: audit + board pointer | — | next |
| **§30-1** | Living Focus calibration + learn filter + `?focus=` | LB-1, LB-2, LB-3 | pending |
| **§30-2** | Focus-scoped chips + trail filter API helper | LB-4, LB-12 (thin) | pending |
| **§30-3** | Trail emit: signal weights + feedback | LB-7, LB-9 | pending |
| **§30-4** | Quarantine message-intel weight renormalize | LB-8 | pending |
| **§30-5** | Alignment nudge → `nudge_expert` or shared helper | LB-8 | pending |
| **§30-6** | Disposition soft-feature in scoring (capped) | LB-5 | pending |
| **§30-7** | Scenario outcome soft-boost in scoring (capped) | LB-6 | pending |
| **§30-8** | RF-2 cockpit KPI + mindmap summary honesty | LB-14, LB-15 | pending |
| **§30-9** | Homepage fetch dedupe (Focus owns trail/pick) | LB-11 | pending |
| **§30-10** | Shared subnet feed for picks + judges | LB-16 | pending |

**Defer unless asked:** LB-10 stub recs (or delete unused path), LB-13 dual portfolio, LB-17 pick_history scoring, full money-flow graph.

---

## §30-1 — Living Focus correctness (ship first)

**AC:**
- [ ] Read `cal.weights` from `/api/calibration/status` (fallback to legacy keys)
- [ ] Learn-strip filter: only events whose netuid matches focus (null netuid ≠ match)
- [ ] `?focus=` / `?netuid=` sets focus on load + scrolls to Living Focus
- [ ] Small JS/unit or contract smoke

**Files:** `static/js/living_focus.js`

---

## §30-2 — Focus-scoped chrome

**AC:**
- [ ] Rug chip stays focus netuid (already)
- [ ] Scenario chip from focus-tagged scenarios or honest-empty
- [ ] Postmortem chip prefers focus SN when present
- [ ] Optional: trail client filter helper shared with learn strip

**Files:** `living_focus.js`

---

## §30-3 — Trail completeness

**AC:**
- [ ] `nudge_signal_weight` emits `weight_change` (or `signal_weight_change`) via trail_bus
- [ ] `LearningEngine.record_feedback` emits trail after nudge
- [ ] Living Focus can show signal lean when event present

**Files:** `weights.py`, `trail_bus.py`, `learning_engine.py`, resolver call sites

---

## §30-4 — Message-intel weight quarantine

**AC:**
- [ ] `adjust_jury_weights` either calls `nudge_expert` with small delta **or** writes dispositions only (no renormalize-to-1.0)
- [ ] Document choice in comment: council multiplicative scale preserved
- [ ] Test that council weights stay in [0.1, 2.0] after intel ingest path

**Files:** `message_intel/self_learning.py` (or equivalent)

---

## §30-5 — Alignment nudge hygiene

**AC:**
- [ ] `apply_alignment_nudge` uses `nudge_expert` (or shared delta helper) + trail already emitted
- [ ] No parallel `save_weights` math

**Files:** `internal/learning/alignment_nudge.py`

---

## §30-6 — Dispositions → score (soft)

**AC:**
- [ ] `score_subnet_for_*` reads soul_map disposition for netuid when present
- [ ] Soft multiplier capped (±5–10%); absent → no-op (honest)
- [ ] Unit test: disposition boost/dampen changes score; missing disposition unchanged

**Files:** `state_vector.py` or daily/hourly pick scoring, soul_map read helper

---

## §30-7 — Scenario outcomes → score (soft)

**AC:**
- [ ] On score, lookup similar scenario tags for netuid/regime; apply capped boost if past outcome correct
- [ ] Cold start: no scenarios → no change
- [ ] Test with fixture scenario_memory

**Files:** `scenario_memory.py`, scoring path

---

## §30-8 — RF-2 honesty

**AC:**
- [ ] Cockpit KPI accuracy only from `trust_banner` (no raw stats fallback)
- [ ] `/api/mindmap/summary` marks stub conviction as `data_available: false` or removes fake 50

**Files:** `cockpit_hydrate.js`, `learning/routes.py`

---

## §30-9 — Homepage fetch dedupe

**AC:**
- [ ] Living Focus consumes shared hydrate cache OR cockpit skips trail/daily-pick when Focus mounted
- [ ] One fewer duplicate of `/api/mindmap/trail` on first paint

**Files:** `cockpit_hydrate.js`, `living_focus.js`

---

## §30-10 — Shared subnet feed

**AC:**
- [ ] Single helper used by picks + judges when chain primary (merged or live)
- [ ] Test: pick row and judge row agree on source label for same netuid in fixture

**Files:** `server.py`, `merged_data.py`, judges routes

---

## Contract

Same as §29 — one PR per slice, contract green, update queue table on merge only.
