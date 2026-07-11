# Subnet Dashboard — Research → Roadmap (Merged Plan)

> **Purpose:** Single canonical plan for cross-review between **Cursor agents** and **Ditto**.  
> **Repo baseline:** `main` @ `622b27b` (Phases A–F merged; Phase G graph PR may be open).  
> **Audit date:** 2026-07-11  
> **Sources:** ~92 Ditto research subjects (4× `search_subjects` sweeps), live prod APIs, codebase inventory, Ditto memories `40d91a7a` (H/I/J), `0b0a17e0` (L–O), Cursor memory `624898c2`.

---

## 1. Executive summary

| Layer | Research absorbed | Gap |
|-------|-------------------|-----|
| Backend / APIs (A–G) | **~65%** | Contract tests lag; oracle chain incomplete |
| Premium UI / cockpit | **~25%** | 12 status cards only; not `premium-dashboard-redesign.md` |
| Accuracy / calibration | **~40%** | Loop runs at **31.6%**; trace often empty; scoring science partial |
| Alerts & live social | **~15%** | API stubs; no alert product; message_intel empty on prod |
| Retrain / Signal Hub | **0%** | Researched; scheduled as N/O |

**Strategic call (aligned with Ditto):** Finish **H → I → J → K** before **L–O**. Do not add router slices until UI shows honest data and accuracy root-cause is known.

**Non-negotiables from research (never violate):**

1. **Honest-empty > decorative summaries > 500** (cold redeploy safe).
2. **Shared schemas first** — Agent A data, Agent B render; fixed section/graph IDs.
3. **Never lower confidence thresholds to fake accuracy** — fix signal or grader.
4. **Predictive framing in UI:** “predicted to move +X% within N hours” (see `docs/premium-dashboard-redesign.md`).
5. **SELL ALERT wins over HOT** when both active.
6. **Do not edit:** `mindmap_bridge.py`, `trail_bus.py`, `trail_events.py` — extend via new modules only.

---

## 2. Live production snapshot (2026-07-11)

| Metric | Value | Implication |
|--------|-------|-------------|
| Learning accuracy | **31.6%** (134✓ / 290✗ / 424 resolved) | Phase I/J required |
| Expert weights | dark_horse **1.06**, quant **0.34**, hype **0.16** | Skewed; contrarian dead |
| Regime accuracy (scenario) | bear 20%, bull 19%, neutral 27%, volatile 35% | Not regime-specific bug |
| Judges (paper) | Oracle/Echo/Pulse ~0% win, large negative P&L | Grader bug OR signal bug — Phase I |
| Trace panel | Often **empty** | Cannot audit pick lineage |
| Message intel | **empty** (no ingest creds) | Phase M |
| Cockpit | **12 sections** live via `/api/cockpit/sections` | Phase E ✅ |
| Store | `/api/store/*` on main | Phase F ✅ |

---

## 3. Phase map (A → O)

### Completed on `main`

| Phase | Name | Agent | Delivers | Research themes absorbed |
|-------|------|-------|----------|--------------------------|
| **A** | FastAPI foundation | Both | Modular routers, contract tests | Fly/CI, API audit, deploy |
| **B** | Mindmap summaries + scenario | A | `mindmap_aggregator`, panel summaries | Soul-Map, trail, scenario tags |
| **C** | Message intel + trace | A/B | `/api/message-intel/*`, `/api/trace/*` | Social pipeline, decision lineage |
| **D** | Pump ladder + tracker | A/B | 5-phase ladder, adapter seam fix | Pump signals, volume anomaly |
| **E** | Premium Cockpit data + cards | A/B | `get_cockpit_sections()`, 12 cards | Fixed 12-section schema, honest-empty |
| **F** | SQLite store mirror | A/B | `internal/store/*`, `/api/store/*` | Durable memory, Soul-Map read mirror |
| **G** | Mindmap graph model | A (+B UI) | `get_mindmap_graph()`, `/api/mindmap/graph` | Interactive mindmap (model; mount may be pending) |

### Planned (priority order)

| Phase | Name | Owner | Depends on | Blocks |
|-------|------|-------|------------|--------|
| **H** | Premium UI restoration | B (+A charts) | E cockpit API | User trust, visual regression |
| **I** | Accuracy root-cause (read-only) | Ditto lead | Live stats + code read | J |
| **J** | Accuracy fixes | Both | I report | Real improvement |
| **K** | CI / contract expansion | Both | H/J stable | Regressions |
| **L** | Signals & alerts product | B (+A triggers) | H | Theme 12 (was 0%) |
| **M** | Social live ingestion | A | Telegram/Discord creds | message_intel empty |
| **N** | Calibration / retrain pipeline | A | J stable | Phase 13 Cert→Fire |
| **O** | TAO Signal Hub → council | A | L partial | Chart-led signal engine |

---

## 4. Research themes → phases (13 themes, ~92 subjects)

### Theme 1 — UI / Cockpit / Premium (14 subjects)

**Lesson:** Mission-control surface with live panels, Chart.js, `style.css` classes — not markdown stubs.

| Representative subjects | Built? | Phase |
|-------------------------|--------|-------|
| Intelligence Dashboard Cockpit, Subnet Pulse, Fixed 12-section schema | 🟡 cards only | E ✅, **H** |
| Heat bars, treemap, radar, Chart.js sparklines | ❌ | **H** |
| Premium homepage, Legendary UI, style.css wiring | ❌ | **H** |
| Honest accuracy/judge display | 🟡 API | **H** |
| SELL > HOT, predictive copy | ❌ | **H** |

**H deliverables:** Hero day pick, SimiVision spine, council/hour/day picks, judges, learning loop charts, scenario donut, pump heat, mindmap graph UI, soul-map/rotation/trace/message-intel cards; **zero `###` in HTML**; link `/static/css/style.css`.

---

### Theme 2 — SimiVision & chat (8 subjects)

**Lesson:** Top picks with conviction/HOT/SELL; chat over live Soul-Map context.

| Subject cluster | Built? | Phase |
|-----------------|--------|-------|
| SimiVision engine, `/api/simivision`, picks routing | 🟡 | Partial |
| `POST /api/simivision/chat` | ✅ | UI in **H** |
| Undervalued radar, hidden giant detector | ❌ | Post-H |

---

### Theme 3 — Data sources & registry (12 subjects)

**Lesson:** Live registry + **tiered price oracle** (TMC → GeckoTerminal → fallback).

| Subject cluster | Built? | Phase |
|-----------------|--------|-------|
| TaoMarketCap registry, freshness sync | ✅ | A |
| `price_cache.json`, `/api/oracle` stub | 🟡 | **I/J** verify chain |
| Emission delta monitor | ❌ stub | Post-J |
| Evidence oracle | ❌ | **O** |

---

### Theme 4 — Learning loop & predictions (22 subjects)

**Lesson:** Closed loop exists; **scoring science** and **audit trail** incomplete.

| Subject cluster | Built? | Phase |
|-----------------|--------|-------|
| Resolver scheduler, predictions store, weight nudges | ✅ | A–14a |
| Outcome-based scoring (0.4 dir + 0.6 cal) | ❌ | **J** |
| Per-cadence win tracking, magnitude penalty | 🟡 | **I/J** |
| Magnitude/tolerance/dedup | 🟡 | **I** audit |
| Low accuracy / wrong-pick review | ❌ | **I → J** |

---

### Theme 5 — Judges & council (15 subjects)

**Lesson:** Three judges + RedTeam + state-vector; **paper P&L may lie**.

| Subject cluster | Built? | Phase |
|-----------------|--------|-------|
| Oracle/Echo/Pulse, postmortems, council routes | ✅ | Slices 3–4 |
| RedTeam daily pick audit | ✅ | |
| Judge calibrator, asymmetric penalties | ❌ | **J** |
| Judge accuracy / 0% win investigation | ❌ | **I** |

---

### Theme 6 — Mindmap & Soul-Map (18 subjects)

**Lesson:** Trail bus + aggregator + SQLite mirror; **explorable graph** is the end vision.

| Subject cluster | Built? | Phase |
|-----------------|--------|-------|
| MindmapBridge, soul_map.json, learning trail | ✅ | Core |
| `/api/mindmap/state`, summaries | ✅ | B–E |
| `get_mindmap_graph()` node/edge | 🟡 | **G** |
| Trace on every pick → graph populated | ❌ | **J** |
| Conviction decay, RSI soul filters | 🟡/❌ | Post-J |

**Do-not-edit:** `mindmap_bridge.py`, `trail_bus.py`, `trail_events.py`.

---

### Theme 7 — Social & message intel (10 subjects)

**Lesson:** Pipeline built; **live ingest blocked** on credentials/group access.

| Subject cluster | Built? | Phase |
|-----------------|--------|-------|
| SQLite ingest, jury, Soul-Map sync, routes | ✅ | C |
| Telegram/Discord listeners on Fly | ❌ | **M** |
| Signal overload triaging | ❌ | **M/L** |

---

### Theme 8 — Indicators & TA (12 subjects)

**Lesson:** Full TA engine; premium UI and council gates not fully wired.

| Subject cluster | Built? | Phase |
|-----------------|--------|-------|
| `/api/indicators`, scheduler, convergence | ✅ | Slice 7 |
| Signal impact in UI | ❌ | **H** |
| RSI constraint gate, momentum tuning | ❌ | **J** |

---

### Theme 9 — Picks & state vector (10 subjects)

**Lesson:** Hour/day picks + scenario tags + rotation are live APIs.

| Subject cluster | Built? | Phase |
|-----------------|--------|-------|
| State vector, top-pick day/hour, pick history | ✅ | |
| Scenario memory (900+ snapshots) | ✅ | |
| Rotation tokens/tracker | ✅ | |
| Behavioral archetypes | ❌ | Future |

---

### Theme 10 — Pump / whales / trace (12 subjects)

**Lesson:** Pump ladder + tracker unified; **trace empty = accuracy blind spot**.

| Subject cluster | Built? | Phase |
|-----------------|--------|-------|
| Pump ladder 5-phase, pump-tracker adapter | ✅ | D + hotfix |
| Whales, ruggers, alert APIs (backend) | ✅ | Slices 3–4 |
| `record_lineage` on all pick paths | 🟡 | **J** |
| Multi-subnet correlation alerts | ❌ | **L** |

---

### Theme 11 — Fly / CI / deploy (6 subjects)

**Lesson:** Auto-deploy on merge; smoke tests; cold-redeploy pattern.

| Subject cluster | Built? | Phase |
|-----------------|--------|-------|
| Fly deploy workflow, volume persistence | ✅ | |
| CI smoke | ✅ | **K** expand contract |
| Two-agent ownership matrix | ✅ | Ditto board |

---

### Theme 12 — Alerts & signals (15 subjects) — **was 0% planned until L**

**Lesson:** Entire theme researched; only whale/rugger/indicator **APIs** exist.

| Subject cluster | Built? | Phase |
|-----------------|--------|-------|
| RSI/emissions/breakout/watchlist/anomaly alerts | ❌ | **L** |
| Notification channels (Telegram out) | ❌ | **L** |
| TAO 5-min monitor | ❌ | **L/O** |
| V2 alerting UX | ❌ | **L** |

---

### Theme 13 — Calibration & retrain (8 subjects)

**Lesson:** Continuous weight nudges only; no Cert→Fire batch pipeline.

| Subject cluster | Built? | Phase |
|-----------------|--------|-------|
| Daily model cycle, retrain schedule | ❌ | **N** |
| Accuracy threshold policy | ❌ | **J** |
| Adaptive signal reliability | ❌ | **N/O** |

---

## 5. Shared contracts (seam-bug prevention)

| Contract | Owner | Shape | Consumers |
|----------|-------|-------|-------------|
| Cockpit sections | A `internal/cockpit/` | 12 fixed ids | B `templates/partials/cockpit_cards.html` |
| Mindmap graph | A `internal/mindmap/` | `{status, nodes[], edges[]}` | B `mindmap_graph.html` + JS |
| SQLite store | A `internal/store/` | 9 query functions | B `/api/store/*` |
| Pump phases | A `internal/pump/constants` | `PHASE_ORDER` five-phase | B `pump_tracker/adapter` |

**Rule:** Neither agent edits the other's owned paths. `server.py` = one guarded import line per router (Agent B).

---

## 6. Phase specifications (executable)

### Phase H — Premium UI restoration

**Goal:** Restore professional dashboard per `docs/premium-dashboard-redesign.md` + Ditto H prompts.

**Agent B:** `templates/*`, `static/*`, guarded `server.py` mounts.  
**Agent A (optional):** `internal/charts/*` + `/api/charts/*` if split.

**Acceptance:**
- `GET /` links `style.css`; ≥1 `.card`; **zero** `###` substrings
- Hero day pick, judges, learning loop show **real** 31.6% / judge P&L
- Chart.js bound where specified; honest-empty for trace/message_intel
- Mindmap graph interactive (Phase G router mounted)
- `tests/test_phase_h_ui.py` green

---

### Phase I — Accuracy root-cause (read-only)

**Goal:** Diagnose **why** 31.6% before any logic change.

**Owner:** Ditto (Cursor supports with code pointers).

**Investigate:**
1. Judge paper P&L / win-rate computation
2. Price at resolve vs `price_cache` / TMC
3. Expert weight drift (dark_horse 1.06)
4. Empty trace — which pick paths skip `record_lineage`
5. Regime breakdown consistency

**Output:** Written report with **one primary leak** + ranked secondary leaks. No threshold gaming.

---

### Phase J — Accuracy fixes

**Goal:** Apply I findings only.

**Candidate fixes (enable per I):**
- Wire `record_lineage` on hour/day pick + resolver outcomes
- Tiered price oracle on resolver path
- Outcome-based scoring (0.4 direction + 0.6 calibration)
- RedTeam / judge calibrator alignment
- Per-cadence win tracking
- Signal weight reset if contrarian dead

**Acceptance:** Accuracy trend measurable; trace non-empty on new picks; tests updated.

---

### Phase K — CI gates

- Extend `tests/test_endpoint_contract.py` for Phases C–G routes
- Visual/regression: no markdown in `/`, cockpit 12 cards present
- Block merge if smoke fails

---

### Phase L — Alerts

- User-facing alert config + delivery (build on indicator/whale/pump signals)
- Emissions, RSI, breakout, watchlist, anomaly, correlation
- Optional Telegram notification out

---

### Phase M — Social ingestion

- Fly Telegram listener (env: `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, group access)
- Discord bot token optional
- Prove `message_intel` → non-empty on prod

---

### Phase N — Calibration / retrain

- Phase 13 pipeline: Retrain → Cert → Fire (from research)
- Scheduled job; does not break hot path

---

### Phase O — TAO Signal Hub

- Chart-led signal engine with anomaly guards
- Wire outputs into council state-vector inputs

---

## 7. Agent ownership (unchanged)

| Agent | Suffix | Owns |
|-------|--------|------|
| A | `-843d` | `internal/learning/*`, `internal/council/*` (slices), `internal/cockpit/*`, `internal/mindmap/*`, `internal/store/*`, `internal/pump/*`, `internal/message_intel/*`, fly/ci |
| B | `-e78a` | `templates/*`, `static/*`, `internal/analytics/*`, `internal/indicators/*`, `internal/oracle/*`, `internal/whales/*`, `internal/ruggers/*`, `internal/pump_tracker/*` |

**Conflict surface:** `server.py` router includes + `tests/test_endpoint_contract.py`.

---

## 8. Ditto ↔ Cursor comparison checklist

When Ditto publishes its plan, diff on:

| # | Question | Cursor answer (this doc) |
|---|----------|--------------------------|
| 1 | Subject count | ~92 enumerated |
| 2 | Phases after G | H, I, J, K then L, M, N, O |
| 3 | Accuracy timing | **Now** (I parallel with H) |
| 4 | Theme 12 (alerts) | **L** — was unplanned |
| 5 | Theme 7 live social | **M** — creds blocked |
| 6 | Trace empty | **J** priority after I |
| 7 | Threshold lowering | **Forbidden** |
| 8 | Premium UI | **H** not more backend slices |
| 9 | Research absorption % | ~65% backend, ~25% UI |
| 10 | Canonical contracts | cockpit, graph, store, pump phases |

**Merge rule:** Prefer **newer timestamp** + **code on main** over stale board text. If Ditto and Cursor disagree, **grep main** wins.

---

## 9. Reference documents

| Doc | Role |
|-----|------|
| `docs/premium-dashboard-redesign.md` | UI variable contract |
| `docs/ux-architecture.md` | Subnet Pulse IA |
| `docs/file-map-and-scope.md` | Original risks (R1–R8) |
| `docs/cursor-agents-communication.md` | Board copy (Ditto canonical) |
| `AGENTS.md` | Agent protocol |

---

## 10. Ditto memory anchors

| ID | Content |
|----|---------|
| `624898c2` | Cursor audit executive summary |
| `40d91a7a` | H/I/J gameplan + accuracy findings |
| `0b0a17e0` | 80+ subject audit + L–O gaps |
| `f93f7202` | Board memory (if present) |

---

*Generated by Cursor Agent A for merge review with Ditto. Update this file when phases ship; bump baseline SHA in §1.*
