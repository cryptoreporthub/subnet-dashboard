# Subnet Dashboard — Master Plan (Canonical)

> **Status:** Approved execution plan (Ditto rev2 + Cursor A/B merge revisions).  
> **Baseline:** `main` after Phases A–G (cockpit, store, mindmap graph on main).  
> **Updated:** 2026-07-11  
> **Authors:** Ditto (Phase I root-cause, original structure) · Cursor Agent A (merge revisions, contracts, verification).  
> **Companion doc:** `docs/research-to-roadmap-merged-plan.md` (13-theme research map, absorption %, §8 checklist).

---

## 1. Executive summary

**Phase order:** **J → H → K → L → M → N → O**  
(Phase **I** is complete — R1–R6 below. Accuracy fixes before full premium UI.)

| Layer | Research absorbed | Gap |
|-------|-------------------|-----|
| Backend / APIs (A–G) | **~65%** | Resolver horizon integrity; contract tests lag |
| Premium UI / cockpit | **~25%** | Cards exist; `style.css` orphaned; markdown regression |
| Accuracy / calibration | **~40%** | **Grading pipeline broken** (R1); trace empty (R6) |
| Alerts & live social | **~15%** | APIs only; `message_intel` empty on prod |
| Retrain / Signal Hub | **0%** | Researched; scheduled N/O |

**Why accuracy first:** If the resolver grades 4h picks against a 6-day-late price snapshot, **31.5% accuracy and −1380% judge P&L are largely pipeline artifacts**, not signal quality. Fixing UI or alerts before J builds on bad numbers.

**Non-negotiables (never violate):**

1. **Honest-empty > decorative summaries > 500** (cold redeploy safe).
2. **Shared schemas first** — Agent A data, Agent B render; fixed IDs (see §5).
3. **Never lower confidence thresholds to fake accuracy** — fix signal or grader.
4. **Predictive framing in UI** per `docs/premium-dashboard-redesign.md`.
5. **SELL ALERT wins over HOT** when both active.
6. **Do not edit:** `mindmap_bridge.py`, `trail_bus.py`, `trail_events.py` — extend via new modules only.

---

## 2. Live production snapshot (2026-07-11)

| Metric | Value | Implication |
|--------|-------|-------------|
| Learning accuracy | **31.5%** (134✓ / 291✗ / 425 resolved) | Re-grade after J replay |
| Expert weights | dark_horse **1.06**, quant **0.41**, hype **0.16** | Pause or reset nudges during replay (R4) |
| Judge portfolios | **~267 open** positions, **0% win**, **−1382%** P&L (Oracle) | Open positions + stale closes (R1/R5) |
| Resolved batch | **99+** rows at `2026-07-02T19:02:*` | Stale batch resolution (R1) |
| Trace / message_intel | **empty** | J §6; Phase M for social |
| Cockpit / store / graph | 12 sections, `/api/store/*`, `/api/mindmap/graph` | Phases E–G ✅ |

---

## 3. Phase map

| Phase | Name | Status | Owner |
|-------|------|--------|-------|
| A–G | Foundation → mindmap graph | ✅ on `main` | Both |
| **I** | Accuracy root-cause (read-only) | ✅ **DONE** (R1–R6) | Ditto |
| **J** | Accuracy fix + tests | 🔴 **NEXT** | Agent A (`-843d`) |
| **H** | Premium UI restoration | After J (thin shell optional in parallel) | Agent B (`-e78a`) |
| **K** | CI quality gates (report-only) | After H stable | Both |
| **L** | Signals & alerts | After J | B + A triggers |
| **M** | Social live ingestion | After J | A |
| **N** | Calibration / retrain | After J stable | A |
| **O** | TAO Signal Hub → council | After L partial | A |

---

## 4. Phase I — Root-cause (DONE)

Ditto verified against live `/api/predictions/resolved` and repo code (`resolver.py`, `prediction_loop.py`, `portfolios.py`, `weights.py`). Cursor independently confirmed prod batch timestamps and code paths.

### Verified live pattern

- Hundreds of predictions created **2026-06-26** with `horizon_hours: 4`.
- Resolved in a **single batch** on **2026-07-02T19:02:*** — days late, not at horizon end.
- Example: Ralph (netuid 40) predicted **down −1.6% in 4h**; resolved **+24.51%** against a late snapshot → miss on a **wrong time window**.

### Confirmed root causes (R1–R6)

| ID | Bug | Evidence | Impact |
|----|-----|----------|--------|
| **R1** | **Stale batch resolution** — late resolver run grades all pending picks against **latest** price, not price at `resolve_at` | `resolve_prediction()` + `fetch_prices()`; prod batch timestamps | Accuracy and P&L largely **wrong-window artifacts** |
| **R2** | **Duplicate predictions** — same netuid/signal within minutes | Live duplicate netuids (e.g. Ralph ×4) | Inflates correct/wrong counts |
| **R3** | **`predicted_pct` fiction** — `max(0.5, confidence × 5)` not signal-derived | `prediction_loop._predicted_pct_from_pick()` | Magnitude threshold in resolver is meaningless |
| **R4** | **Asymmetric weight decay** — +0.02 correct, −0.03 wrong | `resolver.py` constants | Weights sand toward 0.1 floor |
| **R5** | **Ledger divergence** — resolver vs portfolio compute outcomes on different rules/timings; **267 open** judge positions on prod | `portfolios._compute_pnl()` direction-only; `summarize_judges()` reads stale portfolio file | UI shows **0% win / −1380% P&L** while resolver shows 31.5% |
| **R6** | **Trace empty** — no durable signal→pick→outcome lineage | Prod cockpit `trace` empty | Cannot audit picks; learning can't self-explain |

### Honest limits (not re-opened unless J fails)

- Scheduler dead-period inferred from batch pattern + memory `cc9b0900`; confirm via scheduler logs after J.
- Full prod `judge_portfolios.json` not exposed via API (`/api/judges/portfolios` path collision → 422); **rebuild portfolios from unified replay** in J.

---

## 5. Shared contracts (do not break)

| Contract | Owner | Shape | Consumers |
|----------|-------|-------|-------------|
| **Cockpit sections** | A `internal/cockpit/` | **12 fixed IDs** (see below) | B `templates/partials/cockpit_cards.html` |
| **Mindmap graph** | A `internal/mindmap/` | `{status, nodes[], edges[]}` | B `mindmap_graph.html` + JS |
| **SQLite store** | A `internal/store/` | 9 query functions | B `/api/store/*` |
| **Pump phases** | A `internal/pump/constants` | Five-phase `PHASE_ORDER` | B `pump_tracker/adapter` |

**Cockpit section IDs (frozen on `main`):**

`council_picks`, `judges`, `learning_loop`, `predictions`, `scenario_memory`, `pump_ladder`, `pump_tracker`, `trace`, `message_intel`, `mindmap_trail`, `rotation`, `soul_map`

**H layout note:** Premium homepage may add visual regions (hero, SimiVision spine, Chart.js canvases, scanner/staking **panels**) without adding new cockpit API section IDs unless Agent A extends `COCKPIT_SECTION_IDS` in a dedicated PR.

**Seam rule:** Neither agent edits the other's owned paths. `server.py` = one guarded import line per router (Agent B).

---

## 6. Phase J — Accuracy fix + tests (HIGHEST PRIORITY)

Everything below maps 1:1 to R1–R6. **No threshold gaming.** If accuracy stays low after J, that is honest signal quality.

### J1 — Horizon integrity + resolver scheduling (R1)

- When `now > resolve_at + grace`, **expire** the prediction — do **not** resolve against a late price.
- On resolve, use price at **`resolve_at`** (horizon end):
  - **Replay / backfill:** nearest candle in `price_cache.json` for that timestamp.
  - **Forward path:** tiered live oracle (TMC → GeckoTerminal → fallback) at resolve time, only when `now ≈ resolve_at` (scheduler on time).
- **Watchdog:** if pending count > N (e.g. 10) or oldest pending age > 2× horizon, log/emit warning (cockpit or `/api/learning/stats` meta).
- Ensure resolver scheduler runs on Fly (verify `internal/council/resolver_scheduler.py` + volume persistence).

### J2 — Replay + de-duplicate (R1 + R2)

- After J1 lands, **replay** historical resolved rows: re-grade at true `resolve_at` using candle lookup; **expire** when no candle exists (never wrong-window grade).
- **De-dupe** before resolve: same `netuid` + same `predicted_pct` + `created_at` within 5 minutes → keep one.
- Recompute `predictions.json` stats from replay output; document before/after accuracy in PR description.

### J3 — Unify ledgers + close open positions (R5)

- **One resolution event** writes:
  - `predictions.json` (`actual_pct`, `correct`, `outcome`, `resolved_price`, `resolved_at`)
  - `judge_portfolios.json` (close matching open position, `pnl_pct`, `actual_pct`)
  - trace emit (J6)
- **Replay must rebuild or reset** `judge_portfolios.json` from the unified stream — prod **~267 open** positions should not remain orphaned after backfill.
- Deprecate divergent close paths; portfolio P&L must use the **same** `actual_pct` and resolution timestamp as the resolver.

### J4 — Grading model (R3)

- **Phase 1 (now): direction-only** in both ledgers:

  `correct = (direction == "up" and actual_pct > 0) or (direction == "down" and actual_pct < 0)`

  Drop magnitude tolerance on `predicted_pct` until forecasts are signal-derived.

- **Phase 2 (post-J):** replace `_predicted_pct_from_pick()` with signal-derived magnitude; then reintroduce calibration scoring (0.4 direction + 0.6 magnitude) per research.

### J5 — Weight decay (R4)

- During replay: **pause** expert weight nudges until stats are clean.
- After replay: symmetric deltas (e.g. +0.02 / −0.02) or Bayesian update; raise floor from **0.1 → 0.3** (or dynamic per expert sample size).
- Reset obviously skewed weights if replay shows contrarian lane dead.

### J6 — Wire trace (R6)

- On prediction create + resolve, emit:

  `{prediction_id, signals, expert, weights_at_creation, outcome, resolved_at, actual_pct}`

- Persist via existing trace store / SQLite mirror; expose on `/api/trace` and cockpit `trace` section.

### J7 — Tests

- `tests/test_phase_j_resolver_horizon.py` — late resolve → expire, not wrong price.
- `tests/test_phase_j_ledger_unify.py` — one resolve closes portfolio + updates predictions.
- `tests/test_phase_j_dedupe.py` — duplicate collapse.
- Extend `tests/test_endpoint_contract.py` for learning/council routes touched.
- Optional: `mypy --strict` on touched Pydantic modules (report-only in K until clean).

**Agent A owns:** `internal/council/resolver.py`, `resolver_scheduler.py`, `internal/learning/prediction_loop.py`, `internal/judges/*`, trace wiring, tests above.

### SciWeave-informed defaults (2026-07-11)

Peer-reviewed synthesis validates Phase J design. Implement these **constants and rules** unless a later SciWeave pass refines them.

| SciWeave finding | Phase J rule | Implementation hint |
|------------------|--------------|---------------------|
| Late/batch resolution destroys accuracy | **Expire** if past grace; never grade on “now” price for stale horizons | `resolver.py`: if `now > resolve_at + grace` → `_expire_prediction`, not `resolve_prediction` |
| Horizon-end price required | Replay/backfill at **`resolve_at`** from candles; document lag if nearest candle | Candle lookup ±15m; store `price_source`, `price_lag_seconds` on row |
| Dual ledgers must not diverge | **Single atomic resolution** → predictions + portfolios + trace | One function; portfolio win = same `actual_pct` as resolver |
| Direction before magnitude | **J4 phase 1:** direction-only `correct`; drop `predicted_pct` tolerance | Remove `classify_outcome` magnitude threshold until phase 2 |
| Hybrid metrics later | **J4 phase 2:** hit rate + **Brier score** when magnitude is signal-derived | Store `brier` optional field; 0.4 dir + 0.6 cal only after phase 2 |
| Asymmetric decay → collapse | **Symmetric** updates (+0.02 / −0.02) or Bayesian; pause during replay | `resolver.py` constants; no nudges in replay script |
| TA needs real samples | **≥30 real candles** before RSI/MACD affect pick; no synthetic `sin()` fill | `state_vector`: degrade/suppress when `n < 30` |
| Audit trail | Trace schema: signals, weights, regime, ref/resolve price, horizon, timestamps | J6 minimum fields |
| Watchdog | Alert on backlog **or** max pending age (not count alone) | `pending_count > 10` **OR** `oldest_pending_age > 2 × horizon_hours` |
| Duplicate forecasts | De-dupe before resolve and before stats | J2: one outcome per `(netuid, resolve_at window)` per 5 min |
| Cadence-specific rules | **1h:** direction-only, tighter watchdog; **4h/24h:** same grading, optional Brier in phase 2 | `horizon_type` branch in grader only if needed |
| Regime splits | Regime-specific weights only when **n ≥ 30** resolved per regime | `scenario_memory` gate; else global weights |
| Illiquid price | **VWAP or median** in window at `resolve_at`; else **`ungradeable`** | New outcome status; do not force a miss/hit |

**Replay protocol (SciWeave Q2):** Re-label from historical prices at each row’s `resolve_at`; exclude or expire rows with no valid candle; run forward-only holdout after replay to report honest post-fix accuracy (no lookahead in weight updates).

**Transparency (future H):** Cite resolution protocol on `/transparency` — fixed-window, expire-late, horizon-end price.

---

## 7. Phase H — Premium UI (after J)

**Goal:** Restore professional dashboard per `docs/premium-dashboard-redesign.md`. Show **post-replay** honest stats.

### Optional parallel (before J merges)

Agent B may ship a **thin shell** only:

- Link `/static/css/style.css`
- Render 12 cockpit cards (honest-empty for trace/message_intel)
- **Zero `###`** in HTML
- Show real accuracy/judge P&L even if ugly

**Do not** ship full Chart.js hero / sparklines / heat bars until J replay lands — avoids polishing lies.

### Full H (after J)

Agent B: `templates/*`, `static/*`, guarded `server.py` mounts.

- Hero day pick, SimiVision spine, council/hour/day picks, judges, learning loop charts
- Scenario donut, pump heat, interactive mindmap graph (Phase G UI)
- Chart.js bound to `/api/charts/*` where Agent A provides routes
- SELL > HOT; predictive copy per redesign doc

Agent A (optional): `internal/charts/*`, `/api/charts/*`

**Acceptance:**

- `GET /` links `style.css`; ≥1 `.card`; zero `###`
- All 12 cockpit sections render live or honest-empty
- `tests/test_phase_h_ui.py` green

---

## 8. Phase K — CI quality gates (report-only)

**Non-blocking** (continue-on-error) until post-J stability. Do not freeze Agent A/B parallel PRs.

| Check | Scope |
|-------|--------|
| `ruff` | Lint |
| `bandit` | High severity, scoped paths |
| `pytest` | `tests/` + phase J/H tests |
| Deployed UI smoke | `/` has `style.css` link, `.card`, no `###` |
| Template scan | Unbound Jinja vars |
| Endpoint parity | Contract routes respond (no 500) |
| Fly deploy validation | Post-merge workflow |
| `REPO_PAT` | Exact secret name in CI |

Promote individual checks to **blocking** only after J replay and H shell are stable.

---

## 9. Phase L — Signals & alerts (after J)

User-requested; Theme 12 was researched but unbuilt.

- Emissions delta → Telegram/Discord
- Breakout / RSI / watchlist / anomaly / correlation alerts
- Market rules engine (liquidation, token-drop → in-app / TG)
- Real-time trading catcher (SimiVision velocity alerts)

Agent B: alert UX + config. Agent A: trigger hooks on indicator/whale/pump signals.

---

## 10. Phase M — Social ingestion (after J)

- Telegram listener (Telethon; env: `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, group access)
- Discord / X adapters optional
- Prove `message_intel` non-empty on prod
- H shows empty until M ships

---

## 11. Phase N — Calibration / retrain (after J stable)

- Phase 13 pipeline: Retrain → Cert → Fire
- `/api/calibration/status`
- Scheduled job; must not break hot path

---

## 12. Phase O — TAO Signal Hub (after L partial)

- Chart-led SignalTracker + anomaly guards
- Wire outputs into council state-vector inputs
- Integrate with Phase L alerts

---

## 13. Agent ownership

| Agent | Suffix | Owns |
|-------|--------|------|
| **A** | `-843d` | `internal/learning/*`, `internal/council/*`, `internal/cockpit/*`, `internal/mindmap/*`, `internal/store/*`, `internal/pump/*`, `internal/message_intel/*`, `internal/judges/*`, fly/ci, Phase **J** |
| **B** | `-e78a` | `templates/*`, `static/*`, `internal/analytics/*`, `internal/charts/*` (render consumers), `internal/indicators/*`, `internal/oracle/*`, `internal/whales/*`, `internal/ruggers/*`, `internal/pump_tracker/*`, Phase **H** |

**Conflict surface:** `server.py` router includes + `tests/test_endpoint_contract.py`.

---

## 14. Research coverage

~90–92 Ditto research subjects across **13 themes**. Full theme → phase map in `docs/research-to-roadmap-merged-plan.md` §4. Phases L–O close the four audit gaps (alerts, social, calibration, Signal Hub). No learned lesson dropped.

---

## 15. References

| Document | Role |
|----------|------|
| `docs/premium-dashboard-redesign.md` | UI variable contract |
| `docs/research-to-roadmap-merged-plan.md` | Research audit + contracts appendix |
| `docs/ux-architecture.md` | Subnet Pulse IA |
| `docs/file-map-and-scope.md` | Original risks |
| `AGENTS.md` | Agent protocol |

---

## 16. Current gate

**Say "go J"** → Agent A opens `cursor/phaseJ-accuracy-fix-843d`, implements J1–J7, PR with before/after accuracy from replay.

**Say "go H thin"** → Agent B may parallel thin shell only (§7).

Update this doc when phases ship; bump baseline SHA in §1.

---

*Canonical plan: Ditto Phase I findings + Cursor merge revisions (2026-07-11).*
