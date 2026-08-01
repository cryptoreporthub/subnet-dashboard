# AGENT L — Learning loop + Phase C handoff (2026-08-01)

**YOU ARE AGENT L.** Not the hero redesign agent.  
**Sibling:** Agent H → `handoff-agent-h-hero-mindmap-2026-08-01.md` · plan `hero-mindmap-sprint-plan.md` · PR #723  
**Index:** `two-agent-split-2026-08-01.md`

---

## Your objective (only this)

1. Land closed-loop product PRs: **#719 → #720 → #721** (human merges; you babysit)
2. After those are on `main`, ship **Phase C** — mindmap *display* wiring (no weight math)
3. Keep `model-guide.md` ONE Sonnet gate as canon (PR #722)

**Not your job:** Hero B→A, DESIGN-HEAVY mindmap visual spine, merging #692/#675, accuracy lift.

---

## Models (MECHANICAL)

Cite `model-guide.md` — do not fork.

| Role | Model |
|------|--------|
| LOCK | Grok medium → high if stuck (short LOCK only) |
| Build | Composer 2.5 |
| **One Sonnet gate** | **On the Composer diff before push** (low → medium if stuck). Skip Sonnet on LOCK. |

Sonnet finds → Grok fix LOCK → Composer patch → Sonnet re-checks **same gate**. Sonnet never edits.  
Post-build babysit = you/Grok — not a second Sonnet gate.

```text
Grok LOCK → Composer → orchestrator smoke-check → Sonnet on DIFF → push → babysit
```

---

## Baseline

- `main` @ `73a0736` (#718 soul_map I/O gateway) until #719+ merge
- v1 inline worker is prod canon (#706)
- Event-loop wedges fixed (#710–#717)

---

## Open PRs (your merge queue)

| # | What | Notes |
|---|------|-------|
| **#722** | Docs: model-guide + this track handoff | Merge first if still open |
| **#719** | Phase 2: soul_map read cache | MERGEABLE — merge first of product PRs |
| **#720** | Phase A: Judges confidence weights | Rebase onto main after #719 if conflict |
| **#721** | Phase B: Telegram author reliability | Independent of #720 |

**After each merge:** Fly babysit + `curl /health` + spot-check home/mindmap.

---

## Done (context — do not rebuild)

| Phase | Status |
|-------|--------|
| Prod wedge fixes #710–#717 | Done |
| Phase 1 soul_map gateway #718 | On main |
| Phase 2 cache | PR #719 |
| Phase A Judges weights | PR #720 |
| Phase B MI author trust | PR #721 (LB-8 SelfLearning still **quarantined**) |

| System | Closed loop? |
|--------|----------------|
| Council picks | YES |
| Pump Desk | YES |
| Judges | YES after #720 |
| Telegram Pulse | YES after #721 (author trust only) |
| Dev Signals | NO (display-only — Phase C) |

---

## Phase C — your NEXT build (MECHANICAL)

Pure display — **no weight math**. Wire into mindmap summary / trail as appropriate:

1. **Dev Signals** — `data/dev_radar_cache.json` → summary or trail on spikes
2. **Judges portfolios/postmortems** — surface in mindmap summary; optional `judge_weights` after #720
3. **message_intel** — optional author reliability trend block after #721
4. **Pump desk snapshots** — `data/pump_desk/snapshots/` display gap
5. **`store.db::trail_rows`** — **retire/ignore** (live path is `learning_trail` JSON). Do not dual-wire.

Cause-chain “Judges” = council experts (quant/hype/dark_horse/technical), **not** Oracle/Echo/Pulse — do not conflate.

**Branch prefix:** `cursor/phase-c-mindmap-display-<slug>-1d2f`

---

## Files you may touch (Phase C)

- `internal/learning/panel_summaries.py`, `mindmap_aggregator.py` (display only)
- `internal/mindmap/graph.py` / routes only if needed for summary fields
- Tests for new summary/trail fields
- Board STATUS row after merges

**Do not touch:** `council_stage.html` hero redesign, DESIGN-HEAVY CSS for conviction orb, Agent H branches.

---

## Traps

- Do not call `adjust_jury_weights` / `discover_patterns` / `start_background_learning`
- Do not re-enable LB-8 SelfLearning from boot
- Per-judge nudges use `pnl_pct`, not shared prediction `wrong`
- Suite is flaky (~60–70 fails) — compare **failure names**, not counts alone

---

## Paste-ready prompt — AGENT L

```text
You are AGENT L on cryptoreporthub/subnet-dashboard.

READ FIRST:
1. cursor-agents-communication/two-agent-split-2026-08-01.md
2. cursor-agents-communication/handoff-agent-l-learning-loop-2026-08-01.md
3. model-guide.md § Exactly ONE Sonnet gate (via #722 if not on main)
4. AGENTS.md · ponytail

YOU ARE NOT AGENT H. Do not do hero B→A or DESIGN-HEAVY mindmap visual work.
Sibling Agent H owns: handoff-agent-h-hero-mindmap-2026-08-01.md / PR #723.

OBJECTIVE:
1. Babysit merges: #722 (if open) → #719 → #720 → #721 (human merges in GitHub UI)
2. Then Phase C MECHANICAL mindmap display wiring (dev signals, judge portfolios, MI author trend, pump snapshots). No weight math.
3. Retire/ignore store.db trail_rows — do not dual-wire.

MODELS (MECHANICAL):
- Grok medium→high: short LOCK
- Composer 2.5: implement
- Sonnet low→medium: ONE gate on the DIFF before push (not on LOCK)
- Sonnet finds → Grok fix → Composer patch → Sonnet same gate only. Sonnet never edits.

START: Confirm #719–#721 status; if unmerged, post merge checklist for human; when on main, Grok LOCK Phase C then Composer.
Babysit after every merge: /health + home/mindmap spot-check.
```
