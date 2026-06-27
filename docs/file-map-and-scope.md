---
workflow_id: 7194b37f-cf04-4fbf-ae47-48c85f703673
subjob_role: file-map-and-scope
source: ditto-code
sourceContext: project subnet-dashboard
date: 2026-06-17
---

# Subnet Dashboard — File Map & Scope Lock

> Read-only workflow. No code edits performed.

---

## 1. File Map + Goal Lock

### 1.1 Repository layout (code files only)

```
subnet-dashboard/
├── server.py                              # Main Flask entry point (915 LoC)
│   ├── HTTP routes: /, /api/*, /api/signals, /health
│   ├── SimiVision card builder: _build_simivision_choices()
│   ├── Synthetic fallback decisions: _synthesize_decisions()
│   ├── Registry enrichment: _enrich_registry(), _summarize_registry()
│   └── Freshness wrapper: _freshness_meta()
├── internal/
│   ├── freshness.py                       # Background sync + staleness metadata
│   ├── signals/
│   │   └── signal_tracker.py              # Pump-cycle state machine + persistence
│   └── council/
│       ├── orchestrator.py                # Daily-rotation coordinator
│       ├── selector.py                    # Expert consensus + Brain feedback
│       ├── mindmap_bridge.py              # Soul-Map read/write + SimiVision logging
│       ├── input_processor.py             # JSON signal ingestion wrapper
│       ├── emission_monitor.py            # Placeholder emission-delta tracker
│       ├── experts/
│       │   ├── quant.py                   # Emission-based scoring
│       │   ├── hype.py                    # Social-mention sentiment scoring
│       │   └── contrarian.py              # Overvaluation flag scoring
│       ├── judge/
│       │   └── adversarial.py             # Verdict scoring for decisions
│       └── signals/
│           ├── poller.py                  # Poll source → record_signal()
│           └── pathfinder.py              # Route discovery → record_signal()
├── config/
│   ├── registry.json                      # Subnet registry (merged from taostat remote)
│   ├── watchlist.json                     # First-class protocol watchlist
│   └── protocols.json                     # Protocol-name → badge/tag mapping
├── data/
│   ├── soul_map.json                      # Selector output + feedback logs
│   └── signal_timeline.json               # Asset pump-cycle timeline
├── tests/
│   ├── test_selector.py
│   ├── test_judge.py
│   ├── test_signal_tracker.py
│   ├── test_mindmap_bridge_simivision.py
│   ├── test_simivision_contract.py
│   ├── test_freshness.py
│   └── test_server.py
└── templates/
    └── index.html                         # Server-rendered dashboard UI
```

### 1.2 Goal lock by module

| Module | Goal | Primary files | Current entry points |
|--------|------|---------------|----------------------|
| **Council** | Run daily rotation by aggregating expert opinions into subnet decisions | `internal/council/selector.py`, `orchestrator.py`, `experts/*.py` | `Orchestrator.run_daily_rotation()` → `Selector.process_daily_rotation()` |
| **Mindmap** | Persist Selector output, log Brain alignment feedback, serve Brain recommendations | `internal/council/mindmap_bridge.py` | `MindmapBridge.get_brain_recommendations()`, `update_soul_map()`, `log_feedback()` |
| **SimiVision** | Surface top-3 actionable subnet cards with traceability | `server.py::_build_simivision_choices()`, `/api/simivision` | `GET /api/simivision`, homepage `index()` |
| **Persistence** | File-backed state for Soul-Map, signal timeline, registry, watchlist | `data/soul_map.json`, `data/signal_timeline.json`, `config/*.json`, `internal/freshness.py` | Direct JSON read/write via `MindmapBridge`, `SignalTracker`, `freshness.merge_remote_registry()` |
| **Signal ingestion** | Accept asset signals and advance pump-cycle state | `internal/signals/signal_tracker.py`, `internal/council/input_processor.py`, `internal/council/signals/{poller,pathfinder}.py`, server routes `/api/signals` | `POST /api/signals`, `SignalTracker.record_signal()`, `PollerWorker.poll()`, `PathfinderWorker.route()` |

---

## 2. Architecture / Risk Review

### 2.1 Evidence → Signal → Decision → Judge → Learning loop

```
External sources          Council pipeline              UI / persistence
─────────────────────────────────────────────────────────────────────────────
config/registry.json  →   Selector.get_expert_opinions()
                           ├─ QuantExpert (emission)
                           ├─ HypeExpert (social_mentions)
                           └─ ContrarianExpert (is_overvalued)

                          Selector.structure_decision_payload()
                           → consensus_score (weighted 40/30/30)
                           → recommended_action {accumulate, hold, reduce}

                          Selector.track_against_brain()
                           → MindmapBridge.get_brain_recommendations()
                           → MindmapBridge.log_feedback()  (alignment vs Brain)
                           → MindmapBridge.update_soul_map() → data/soul_map.json

POST /api/signals     →   SignalTracker.record_signal()
                           → pump state machine (idle → pumping → pumped → resurging)
                           → data/signal_timeline.json

server.py             →   _build_simivision_choices()
                           ├─ reads soul_map decisions
                           ├─ reads Brain recommendations
                           ├─ reads registry metadata
                           ├─ AdversarialJudge.judge_decision()  (display verdict)
                           └─ MindmapBridge.get_simivision_feedback_boost()

User feedback         →   /api/mindmap/feedback (stored, not yet applied)
                           → MindmapBridge.log_simivision_feedback() (exists, not wired to API)
```

### 2.2 Current data flow paths

1. **Registry refresh**: `freshness.start_background_sync()` → periodic `merge_remote_registry()` → `config/registry.json`.
2. **Daily rotation**: `Orchestrator.run_daily_rotation()` → `Selector.process_daily_rotation()` → expert analysis → decision payload → `MindmapBridge` persistence + feedback logging.
3. **SimiVision render**: `index()` / `get_simivision()` → load `soul_map.json` → `_build_simivision_choices()` → fallback synthesis if decisions are empty → return JSON or render template.
4. **Signal ingestion**: `POST /api/signals` → `_signal_tracker.ingest_intelligence()` → `record_signal()` → state machine → `data/signal_timeline.json`.

### 2.3 Key risks

| # | Risk | Evidence | Impact |
|---|------|----------|--------|
| R1 | **Server.py is a god file** | 915 LoC; contains routing, enrichment, SimiVision synthesis, summary logic | Hard to test; SimiVision changes risk breaking unrelated routes |
| R2 | **SimiVision fallback duplicates Selector logic** | `_synthesize_decisions()` re-implements quant/hype/contrarian heuristics | Divergence between live selector scores and fallback cards |
| R3 | **Learning loop is mostly logged, not learned** | `log_feedback()` and `log_simivision_feedback()` write state but no code consumes feedback to adjust expert weights or decisions | Feedback data exists but does not improve future outputs |
| R4 | **AdversarialJudge is display-only** | Called inside `_build_simivision_choices()` only to populate `judge_verdict` | Judge verdicts do not feed back into Selector or Soul-Map |
| R5 | **No automated signal collection** | `PollerWorker`/`PathfinderWorker` only wrap `record_signal()`; no scheduled polling or external adapters | Pump-cycle state relies on manual `POST /api/signals` |
| R6 | **Emission monitor is a stub** | `EmissionMonitor.check_emission_deltas()` returns zeros and `trend: stable` | Missing real trend/evidence input for Quant expert |
| R7 | **Feedback endpoint is one-way** | `post_feedback()` returns the payload but does not call `log_simivision_feedback()` | User/outcome feedback is dropped |
| R8 | **Soul-Map output is hard-coded date** | `Selector.process_daily_rotation()` sets `"date": "2026-06-10"` | Freshness metadata is misleading |

---

## 3. Staged Implementation Plan + Verification Gates

### Stage 0 — Baseline & safety
- Run existing tests, fix import/environment issues, snapshot coverage.
- **Gate**: `pytest tests/` passes for the modules we will touch.

### Stage 1 — Extract SimiVision engine from server.py
- Move `_build_simivision_choices()` and `_synthesize_decisions()` to `internal/council/simivision.py`.
- Keep `server.py` routes thin (import + call).
- **Gate**: `GET /api/simivision` and homepage render identical payloads; existing tests still pass.

### Stage 2 — Wire the feedback loop
- Connect `POST /api/mindmap/feedback` to `MindmapBridge.log_simivision_feedback()`.
- Use `get_simivision_feedback_boost()` in `Selector.structure_decision_payload()` consensus score.
- **Gate**: new tests verify feedback changes future rankings; `test_mindmap_bridge_simivision` passes.

### Stage 3 — Make Judge verdicts influence decisions
- Have `Selector` call `AdversarialJudge.judge_decision()` on each structured payload.
- Store verdict in decision payload; use low-verdict cases to downgrade confidence or flag review.
- **Gate**: judge verdicts appear in `/api/daily-rotation` output; `test_judge.py` passes.

### Stage 4 — Real signal ingestion + emission trends
- Implement `EmissionMonitor.check_emission_deltas()` against historical registry snapshots.
- Add a lightweight scheduler/background worker that polls configured signal sources.
- **Gate**: pump-cycle transitions without manual `POST`; emission trend data feeds Quant expert.

### Stage 5 — Cleanup and hardening
- Remove hard-coded date in `Selector.process_daily_rotation()`.
- Add fallback provenance metadata to SimiVision payload.
- Add error boundaries so missing `soul_map.json` never crashes homepage.
- **Gate**: all tests pass; `/health` remains green; homepage renders with empty or partial data.

---

## 4. Quick reference: entry points for follow-on work

| Task | Start here |
|------|------------|
| Change how daily rotation decisions are made | `internal/council/selector.py::process_daily_rotation()` |
| Persist or read Soul-Map state | `internal/council/mindmap_bridge.py` |
| Change SimiVision cards | `server.py::_build_simivision_choices()` (target: extract to `internal/council/simivision.py`) |
| Ingest or query signals | `internal/signals/signal_tracker.py::record_signal()` / `ingest_intelligence()` |
| Background sync / freshness | `internal/freshness.py::start_background_sync()` / `refresh_all()` |
| Apply judge verdicts to decisions | `internal/council/judge/adversarial.py` → `internal/council/selector.py` |
| Surface user feedback | `server.py::post_feedback()` → `MindmapBridge.log_simivision_feedback()` |
| Subnet state vector | `server.py::get_subnet_state()` → `GET /api/subnets/{netuid}/state` |
| Top Pick of the Hour / Day | `server.py::get_top_pick_hour()` / `get_top_pick_day()` → `GET /api/top-pick/hour` / `GET /api/top-pick/day` |
| SimiVision jargon tooltips | `templates/index.html` (`.jargon-term`, `.simi-tooltip`, glossary JS) + `static/css/style.css` |
