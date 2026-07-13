# Phase O — TAO Signal Hub → Council (Grok design → Composer spec)

**Date:** 2026-07-13  
**Model:** grok-4.5-xhigh design pass → Composer build  
**Stack:** FastAPI + Uvicorn (`server:app`)  
**main:** `cc6de08` (post-Phase N)

## Verdict: ✅ PROCEED

Substantial signal infrastructure already exists. Phase O adds a **chart-led hub layer** that monitors subnet/TAO metrics, runs anomaly guards, emits rows into Phase L's `SignalStore`, and optionally enriches council scoring — without touching resolver, grading, or learning weight logic.

---

## 0. Naming (avoid collisions)

| Name | Location | Role |
|------|----------|------|
| **Pump-cycle `SignalTracker`** | `internal/signals/signal_tracker.py` | Asset attention lifecycle (TAO pump/resurge) — **unchanged** |
| **Phase L signal pipeline** | `internal/signals/pipeline.py` | Council score → `data/signals.json` — **unchanged core** |
| **TAO Signal Hub (`HubTracker`)** | `internal/signal_hub/` | **Phase O** — anomaly monitors + L bridge + council overlay |
| **WS `get_signal_hub()`** | `internal/signals/ws_hub.py` | WebSocket broadcast — unrelated name collision |

---

## 1. SignalTracker architecture (Hub)

**HubTracker** is a **stateless cycle runner** (not a long-running process by default). Each cycle:

1. Load subnet snapshot (`pipeline.load_subnets()`).
2. Load `data/price_cache.json` candle history.
3. Optionally read message-intel stats (Phase M) — honest-empty if unavailable.
4. Run **monitors** → raw anomaly candidates.
5. Apply **anomaly guards** (thresholds, z-score, ROC, min candles).
6. Publish to Phase L via `SignalStore.append_many()` + `AlertEngine.create_alert()`.
7. Persist hub state to `data/signal_hub_state.json` (overlay cache for council).

**Default cadence:** on-demand (`GET /api/signal-hub/status?refresh=1`) + optional daemon scheduler (`SIGNAL_HUB_AUTO=on`, 15 min).

**Signals tracked:**

| Monitor | Metric | Guard |
|---------|--------|-------|
| `price_population_z` | 24h % change vs all subnets | \|z\| ≥ 2.0 |
| `price_roc` | Rate-of-change from last N candles | \|Δ%\| ≥ 5% over window |
| `volume_spike` | Volume vs rolling mean (cached candles) | ratio ≥ 2.5× |
| `tao_breadth` | Market-wide avg 24h change | \|avg\| ≥ 8% (system alert) |
| `social_shift` | Message-intel conviction (optional M) | conviction ≥ 70 on subnet |

---

## 2. Anomaly guards (exact thresholds)

Env-tunable defaults:

| Constant | Default | Meaning |
|----------|---------|---------|
| `HUB_ZSCORE_THRESHOLD` | `2.0` | Population z-score on `price_change_24h` |
| `HUB_ROC_PCT` | `5.0` | Min % move over ROC window |
| `HUB_ROC_WINDOW` | `6` | Candles for ROC (need ≥30 total for TA guards) |
| `HUB_VOLUME_SPIKE_RATIO` | `2.5` | Volume / rolling mean |
| `HUB_MIN_CANDLES` | `30` | SciWeave TA minimum — skip TA guards below |
| `HUB_TAO_BREADTH_PCT` | `8.0` | Market-wide 24h move alert |
| `HUB_OVERLAY_MAX_BOOST` | `0.05` | Max expert nudge from hub overlay |
| `HUB_SOCIAL_CONVICTION` | `70` | Min conviction for social_shift monitor |

**False-positive mitigation:** require ≥2 independent guard hits OR z≥2.5 for single-metric fire; `dedupe_key` on alerts; Phase L `ALERT_DEDUP_WINDOW_MINUTES` applies.

---

## 3. Council state-vector integration

**State vector** = per-subnet feature bundle in `internal/council/state_vector.py` (`score_subnet_for_hour`, `_expert_contributions`, `_compute_signal_impact`).

**Integration model: enrich input only**

- Hub builds `hub_overlay: Dict[int, Dict]` keyed by netuid:

```json
{"anomaly_score": -0.6, "direction": "bearish", "types": ["price_population_z"], "confidence": 0.72}
```

- `pipeline._market_context()` merges `get_cached_hub_overlay()` into `market_context["hub_overlay"]`.
- `score_subnet_for_hour` calls `apply_hub_overlay(experts, overlay)` — bounded ±0.05 per expert, **no change** when hub inactive/empty.

**Does NOT change:** pick selection algorithm, resolver, weights, grading.

---

## 4. L alert hooks (decoupled)

```
HubTracker.run_cycle()
  → l_bridge.publish(hub_signals, anomalies)
       → SignalStore.append_many()     # data/signals.json
       → AlertEngine.create_alert()    # data/alerts.json
       → (optional) correlation via existing evaluate_correlation_alerts on next L refresh
```

**Coupling rules:**

- Hub imports **public** L APIs only: `SignalStore`, `AlertEngine`, `rules.alert_dedupe_key` patterns.
- Hub does **not** import `correlation.py` internals or modify `rules.py`.
- Alert types: `hub_anomaly`, `hub_tao_breadth`; dedupe `hub_{type}_{netuid}`.
- Same pattern as `internal/message_intel/signals_bridge.py` (Phase M).

---

## 5. TAO integration

**TAO Signal Hub** = Bittensor subnet dashboard signal layer:

- Tracks **subnet token** metrics across ~129 netuids (price, volume, 24h change from taomarketcap/registry).
- **TAO breadth** monitor = aggregate subnet market move (proxy for ecosystem risk-on/off).
- Does **not** replace subnet listing; **feeds** council + L alerts with anomaly-tagged events.
- Pump-cycle `SignalTracker` remains for asset-level (e.g. "TAO" symbol) social pump timing — orthogonal.

---

## 6. Data sources

| Source | Use |
|--------|-----|
| `pipeline.load_subnets()` | Live/registry subnet snapshot |
| `data/price_cache.json` | Candles for ROC, volume spike |
| `data/signals.json` | **Write** via SignalStore (L consumer) |
| `data/signal_hub_state.json` | Hub cycle state + overlay cache |
| `message_intel` (M) | Optional social_shift — skip if empty |
| N retrained weights | **Optional** — `_market_context` already loads weights; hub does not require N |

**Dependencies:** **L required** (store + alerts). **M optional** (social monitor). **N optional** (weights already in market_context).

---

## 7. API surface

### `GET /api/signal-hub/status`

```json
{
  "status": "ok",
  "hub": {
    "active": true,
    "last_cycle_at": "2026-07-13T03:00:00Z",
    "trackers": ["price_population_z", "price_roc", "volume_spike", "tao_breadth"],
    "anomaly_count": 3,
    "signals_emitted": 2,
    "scheduler": {"auto": false}
  },
  "thresholds": { "zscore": 2.0, "roc_pct": 5.0, ... }
}
```

Query `?refresh=1` runs one hub cycle before responding.

### `GET /api/signal-hub/signals`

```json
{
  "status": "ok",
  "signals": [],
  "meta": {"count": 0, "source": "signal_hub"}
}
```

Honest-empty `[]` when no anomalies. Returns last hub-emitted signals from hub state (not full L log).

---

## 8. Failure modes

| Failure | Behavior |
|---------|----------|
| Hub crash / disabled | Council scores without overlay; L pipeline unchanged |
| No price_cache candles | Skip ROC/volume guards; population z may still run on 24h field |
| message_intel empty | `social_shift` monitor reports `skipped` |
| False positive spike | Dedup + dual-guard rule; tune env thresholds |

---

## 9. File list (Composer)

| Action | Path |
|--------|------|
| **Create** | `internal/signal_hub/__init__.py` |
| **Create** | `internal/signal_hub/anomaly.py` |
| **Create** | `internal/signal_hub/tracker.py` — `HubTracker` |
| **Create** | `internal/signal_hub/l_bridge.py` |
| **Create** | `internal/signal_hub/overlay.py` |
| **Create** | `internal/signal_hub/state.py` |
| **Create** | `internal/signal_hub/routes.py` |
| **Create** | `internal/signal_hub/context.py` |
| **Modify** | `internal/signals/pipeline.py` — merge hub overlay into `_market_context` |
| **Modify** | `internal/council/state_vector.py` — 5-line `apply_hub_overlay` hook in `score_subnet_for_hour` |
| **Modify** | `internal/signals/routes.py` — include hub router |
| **Modify** | `server.py` — Jinja `build_signal_hub_context()` only |
| **Create** | `tests/test_phase_o_signal_hub.py` |
| **Modify** | `tests/test_endpoint_contract.py` |

**Do not modify:** resolver, grading, calibration, templates, CSS.

---

## 10. Function signatures

```python
# internal/signal_hub/anomaly.py
def population_zscore(value: float, population: list[float]) -> float: ...
def rate_of_change_pct(closes: list[float], window: int) -> Optional[float]: ...
def volume_spike_ratio(volumes: list[float]) -> Optional[float]: ...
def evaluate_subnet_anomalies(sn: dict, *, cache: dict, population_changes: list[float]) -> list[dict]: ...

# internal/signal_hub/tracker.py
class HubTracker:
    def run_cycle(self, *, persist: bool = True) -> dict[str, Any]: ...

# internal/signal_hub/l_bridge.py
def hub_signals_to_store_rows(anomalies: list[dict]) -> list[dict]: ...
def publish_to_phase_l(anomalies: list[dict], *, persist_signals: bool = True) -> dict[str, Any]: ...

# internal/signal_hub/overlay.py
def build_hub_overlay(anomalies: list[dict]) -> dict[int, dict]: ...
def apply_hub_overlay(experts: dict[str, float], overlay: Optional[dict]) -> dict[str, float]: ...
def get_cached_hub_overlay() -> dict[int, dict]: ...

# internal/signal_hub/state.py
def load_hub_state() -> dict: ...
def save_hub_state(patch: dict) -> None: ...

# internal/signal_hub/routes.py
@router.get("/api/signal-hub/status") -> dict: ...
@router.get("/api/signal-hub/signals") -> dict: ...
```

---

## 11. Acceptance mapping

| Criterion | Implementation |
|-----------|----------------|
| Emits on anomaly | `HubTracker.run_cycle` + guards |
| L rules without coupling | `l_bridge.publish_to_phase_l` → Store + AlertEngine |
| `/api/signal-hub/status` | `routes.py` |
| `/api/signal-hub/signals` | honest-empty list |
| Council degrades gracefully | overlay optional in `score_subnet_for_hour` |
| Tests + `/health` | `test_phase_o_signal_hub.py` + contract |

---

*Design: Phase O per model-guide.md §4. Implementation: Composer.*
