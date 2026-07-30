"""
Council Weights — load / save / regime-aware adjustment of expert weights.

Weights persist in data/soul_map.json under `adversarial_state.council_weights`
(the canonical location read by MindmapBridge.get_expert_weights() and the
Selector). This keeps the learning loop's weight updates flowing straight
into the next pick generation.

Signal weights (per-signal, per-horizon) are also stored in the same file under
`adversarial_state.signal_weights` and are nudged individually when predictions
resolve (Option C — two-tier weighted scoring architecture).
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

DEFAULT_WEIGHTS = {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}
SOUL_MAP_PATH = os.path.join("data", "soul_map.json")

# Signal weight learning constants (shared with resolver.py)
_LEARNING_DELTA_CORRECT = 0.02
_LEARNING_DELTA_WRONG = -0.03
_LEARNING_MIN_WEIGHT = 0.1
_LEARNING_MAX_WEIGHT = 2.0

# Market-impact tilt: 0 = ignore size, 1 = default, 2 = aggressive small-cap bias.
DEFAULT_IMPACT_STRENGTH = 1.0
_IMPACT_STRENGTH_MIN = 0.0
_IMPACT_STRENGTH_MAX = 2.0
_IMPACT_STRENGTH_DELTA = 0.02

# Per-signal, per-horizon default weights
DEFAULT_SIGNAL_WEIGHTS: Dict[str, Dict[str, float]] = {
    "hour": {
        "rsi_crossover": 1.0,
        "macd_cross": 1.0,
        "stochastic_reversal": 1.0,
        "momentum_shift": 1.0,
        "bollinger_squeeze": 1.0,
        "mfi_flow": 1.0,
        "cci_divergence": 1.0,
        "williams_r": 1.0,
        "keltner_channel": 1.0,
        "delegation_flow": 1.0,
        "staking_conviction": 1.0,
        "emission_momentum": 1.0,
        "registration_cost": 1.0,
    },
    "day": {
        "rsi_crossover": 1.0,
        "macd_cross": 1.0,
        "stochastic_reversal": 1.0,
        "momentum_shift": 1.0,
        "bollinger_squeeze": 1.0,
        "mfi_flow": 1.0,
        "cci_divergence": 1.0,
        "williams_r": 1.0,
        "keltner_channel": 1.0,
        "delegation_flow": 1.0,
        "staking_conviction": 1.0,
        "emission_momentum": 1.0,
        "registration_cost": 1.0,
    },
}

# Regime -> per-expert multiplier. >1 boosts, <1 dampens.
REGIME_ADJUSTMENTS: Dict[str, Dict[str, float]] = {
    "risk_on": {"quant": 1.05, "hype": 1.10, "dark_horse": 0.95, "technical": 1.05},
    "risk_off": {"quant": 1.05, "hype": 0.85, "dark_horse": 1.10, "technical": 1.05},
    "chop": {"quant": 1.00, "hype": 0.95, "dark_horse": 1.00, "technical": 1.00},
    "high_volatility": {"quant": 0.95, "hype": 1.05, "dark_horse": 0.95, "technical": 1.10},
}


def _load_raw(path: str = SOUL_MAP_PATH) -> Dict[str, Any]:
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_raw(data: Dict[str, Any], path: str = SOUL_MAP_PATH) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass


def normalize_council_weights(raw: Dict[str, float]) -> Dict[str, float]:
    """Merge legacy ``contrarian`` into ``dark_horse``; return canonical experts only.

    When both keys exist, prefer ``dark_horse`` (the actively nudged slot). The old
    ``max(contrarian, dark_horse)`` merge pinned stale high contrarian values and
    masked downward learning on dark_horse.
    """
    merged: Dict[str, float] = {}
    contrarian = 0.0
    for key, val in (raw or {}).items():
        name = str(key).lower().strip()
        try:
            fval = float(val)
        except (TypeError, ValueError):
            continue
        if name == "contrarian":
            contrarian = max(contrarian, fval)
            continue
        if name in ("darkhorse", "dark_horse"):
            name = "dark_horse"
        merged[name] = fval
    if contrarian and "dark_horse" not in merged:
        merged["dark_horse"] = contrarian
    out = dict(DEFAULT_WEIGHTS)
    for name in DEFAULT_WEIGHTS:
        if name in merged:
            out[name] = merged[name]
    return out


def _raw_has_legacy_contrarian(data: Dict[str, Any]) -> bool:
    """True when soul_map still stores a separate contrarian weight key."""
    for slot in (
        (data.get("adversarial_state") or {}).get("council_weights"),
        data.get("expert_weights"),
        (data.get("soul_map_state") or {}).get("expert_weights"),
    ):
        if not isinstance(slot, dict):
            continue
        if any(str(k).lower().strip() == "contrarian" for k in slot):
            return True
    return False


ARCHIVE_REPLAY_MIN_CURRENT = 5
PREDICTIONS_ARCHIVE_DIR = os.environ.get("PREDICTIONS_ARCHIVE_DIR", "data/predictions_archive")
# ponytail: ±6% from 1.0 still reads as EVEN in UI after a single nudge (e.g. quant 1.04)
NEAR_FLAT_MAX_DEVIATION = 0.06


def _row_replay_key(row: Dict[str, Any]) -> str:
    rid = row.get("id")
    if rid is not None and str(rid).strip():
        return str(rid)
    return f"{row.get('netuid')}-{row.get('created_at')}-{row.get('resolved_at')}"


def _load_predictions_blob(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def _replay_rows_from_blob(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    from internal.council.grading import is_pump_desk_claim

    rows = [
        row
        for row in (data.get("resolved") or [])
        if isinstance(row, dict)
        and row.get("correct") is not None
        and row.get("outcome") not in _SKIP_OUTCOMES
        and not is_pump_desk_claim(row)
    ]
    rows.sort(key=lambda row: str(row.get("resolved_at") or row.get("created_at") or ""))
    return rows


def _archive_replay_rows(archive_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load pre-epoch archive resolved rows for weight replay when current epoch is thin."""
    root = archive_dir or PREDICTIONS_ARCHIVE_DIR
    try:
        from scripts.measure_accuracy_archive import load_archive

        blob = load_archive(root)
    except Exception:
        return []
    return _replay_rows_from_blob(blob)


def merged_replay_rows(
    predictions_path: Optional[str] = None,
    *,
    include_archive: bool = True,
    archive_dir: Optional[str] = None,
    min_current_for_archive: int = ARCHIVE_REPLAY_MIN_CURRENT,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Current-epoch rows plus archive backfill when graded count is below threshold."""
    path = predictions_path
    if path is None:
        from internal.learning.predictions_store import PREDICTIONS_PATH

        path = PREDICTIONS_PATH
    current = _replay_rows_from_blob(_load_predictions_blob(path))
    meta: Dict[str, Any] = {
        "current_graded": len(current),
        "archive_graded": 0,
        "archive_used": False,
        "total_graded": len(current),
    }
    if not include_archive or len(current) >= min_current_for_archive:
        return current, meta

    archive_rows = _archive_replay_rows(archive_dir)
    meta["archive_graded"] = len(archive_rows)
    if not archive_rows:
        return current, meta

    seen = {_row_replay_key(row) for row in current}
    merged = list(current)
    for row in archive_rows:
        key = _row_replay_key(row)
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    merged.sort(key=lambda row: str(row.get("resolved_at") or row.get("created_at") or ""))
    meta["archive_used"] = True
    meta["total_graded"] = len(merged)
    return merged, meta


def count_merged_replay_rows(
    predictions_path: Optional[str] = None,
    *,
    include_archive: bool = True,
) -> int:
    """Graded replay row count, including archive when current epoch is thin."""
    _, meta = merged_replay_rows(predictions_path, include_archive=include_archive)
    return int(meta.get("total_graded") or 0)


def replay_weights_from_predictions(
    predictions_path: Optional[str] = None,
    *,
    include_archive: bool = True,
) -> Dict[str, float]:
    """Rebuild council weights by replaying graded prediction nudges from defaults."""
    from internal.council.signal_expert import expert_for_replay_row

    rows, _ = merged_replay_rows(predictions_path, include_archive=include_archive)
    weights = dict(DEFAULT_WEIGHTS)
    for row in rows:
        expert = expert_for_replay_row(row)
        if not expert or expert not in weights:
            continue
        delta = _LEARNING_DELTA_CORRECT if row.get("correct") else _LEARNING_DELTA_WRONG
        weights[expert] = round(
            max(
                _LEARNING_MIN_WEIGHT,
                min(_LEARNING_MAX_WEIGHT, float(weights[expert]) + delta),
            ),
            4,
        )
    return weights


def soft_blend_weights(
    replayed: Dict[str, float],
    *,
    prior: Optional[Dict[str, float]] = None,
    replay_share: float = 0.7,
) -> Dict[str, float]:
    """Soft reset: blend replayed weights with prior (defaults when omitted)."""
    base = prior if prior is not None else dict(DEFAULT_WEIGHTS)
    share = max(0.0, min(1.0, float(replay_share)))
    out: Dict[str, float] = {}
    for name in DEFAULT_WEIGHTS:
        r = float(replayed.get(name, DEFAULT_WEIGHTS[name]))
        p = float(base.get(name, DEFAULT_WEIGHTS[name]))
        out[name] = round(share * r + (1.0 - share) * p, 4)
    return normalize_council_weights(out)


def rebalance_council_weights(
    *,
    predictions_path: Optional[str] = None,
    soul_map_path: Optional[str] = None,
    replay_share: float = 0.7,
    save: bool = True,
) -> Dict[str, Any]:
    """Slice R — replay ledger with re-attribution, soft-blend, optional persist."""
    from internal.council.grading import is_pump_desk_claim
    from internal.council.signal_expert import expert_for_replay_row

    path = predictions_path
    if path is None:
        from internal.learning.predictions_store import PREDICTIONS_PATH

        path = PREDICTIONS_PATH
    soul = soul_map_path or SOUL_MAP_PATH
    before = load_weights(soul)
    merged_rows, merge_meta = merged_replay_rows(path)
    replayed = replay_weights_from_predictions(path)
    blended = soft_blend_weights(replayed, prior=dict(DEFAULT_WEIGHTS), replay_share=replay_share)

    rows_skipped_pump = 0
    try:
        data = _load_predictions_blob(path)
        for row in (data.get("resolved") or []) if isinstance(data, dict) else []:
            if not isinstance(row, dict) or row.get("correct") is None:
                continue
            if row.get("outcome") in _SKIP_OUTCOMES:
                continue
            if is_pump_desk_claim(row):
                rows_skipped_pump += 1
    except Exception:
        pass

    rows_replayed = sum(1 for row in merged_rows if expert_for_replay_row(row))

    if save:
        save_weights(blended, soul)
        try:
            from internal.learning.trail_bus import emit_weight_change

            for name in DEFAULT_WEIGHTS:
                if abs(float(blended.get(name, 0)) - float(before.get(name, 0))) > 0.001:
                    emit_weight_change(
                        name,
                        before=float(before.get(name, 1.0)),
                        after=float(blended.get(name, 1.0)),
                        reason="council_rebalance",
                    )
        except Exception:
            pass

    return {
        "ok": True,
        "saved": bool(save),
        "replay_share": replay_share,
        "rows_replayed": len(merged_rows),
        "rows_skipped_pump": rows_skipped_pump,
        "archive_used": bool(merge_meta.get("archive_used")),
        "current_graded": int(merge_meta.get("current_graded") or 0),
        "archive_graded": int(merge_meta.get("archive_graded") or 0),
        "before": before,
        "replayed": replayed,
        "after": blended,
    }


def repair_stale_contrarian_weights(
    path: str = SOUL_MAP_PATH,
    predictions_path: Optional[str] = None,
) -> bool:
    """Drop legacy contrarian slot and replay learned weights from the ledger."""
    data = _load_raw(path)
    if not _raw_has_legacy_contrarian(data):
        return False
    if predictions_path is None:
        base = os.path.dirname(path) or "data"
        predictions_path = os.path.join(base, "predictions.json")
    weights = replay_weights_from_predictions(predictions_path)
    save_weights(weights, path)
    return True


def load_weights(path: Optional[str] = None) -> Dict[str, float]:
    """Read learned weights from soul_map.json, defaulting to DEFAULT_WEIGHTS."""
    path = path or SOUL_MAP_PATH
    if repair_stale_contrarian_weights(path):
        data = _load_raw(path)
    else:
        data = _load_raw(path)
    adv = data.get("adversarial_state")
    if isinstance(adv, dict) and isinstance(adv.get("council_weights"), dict):
        return normalize_council_weights(adv["council_weights"])
    sms = data.get("soul_map_state")
    if isinstance(sms, dict) and isinstance(sms.get("expert_weights"), dict):
        return normalize_council_weights(sms["expert_weights"])
    if isinstance(data.get("expert_weights"), dict):
        return normalize_council_weights(data["expert_weights"])
    return dict(DEFAULT_WEIGHTS)


def load_weights_for_ui(path: Optional[str] = None) -> Dict[str, float]:
    """split_v2 web — read council weights from worker volume when local data is absent."""
    from internal.data_volume import needs_worker_volume_proxy

    if needs_worker_volume_proxy():
        try:
            from internal.worker_proxy import fetch_learning_stats_sync

            data = fetch_learning_stats_sync()
            expert_weights = data.get("expert_weights")
            if isinstance(expert_weights, dict) and expert_weights:
                return normalize_council_weights(expert_weights)
        except Exception:
            pass
    return load_weights(path)


def weights_are_default_flat(weights: Optional[Dict[str, float]] = None) -> bool:
    """True when every expert is still at the neutral 1.0 baseline."""
    src = weights if isinstance(weights, dict) else load_weights()
    return all(abs(float(src.get(name, 1.0)) - DEFAULT_WEIGHTS[name]) < 0.001 for name in DEFAULT_WEIGHTS)


def weights_are_near_flat(
    weights: Optional[Dict[str, float]] = None,
    *,
    max_deviation: float = NEAR_FLAT_MAX_DEVIATION,
) -> bool:
    """True when all experts are within max_deviation of the 1.0 baseline."""
    src = weights if isinstance(weights, dict) else load_weights()
    band = max(0.0, float(max_deviation))
    return all(abs(float(src.get(name, 1.0)) - DEFAULT_WEIGHTS[name]) <= band for name in DEFAULT_WEIGHTS)


def maybe_rebalance_council_weights_on_boot() -> Optional[Dict[str, Any]]:
    """One-shot archive-aware rebalance on the volume owner (worker / inline volume).

    Runs when weights still look EVEN (near-flat) and the merged ledger has enough
    graded rows — including archive backfill when the current epoch is thin.
    """
    from internal.data_volume import data_dir_is_mounted_volume, has_local_volume_data
    from internal.run_mode import is_worker_mode

    owns_volume = is_worker_mode() or (
        data_dir_is_mounted_volume() and has_local_volume_data()
    )
    if not owns_volume:
        return None

    flag = os.environ.get("COUNCIL_WEIGHT_REBALANCE_ON_BOOT", "off").strip().lower()
    force = flag in ("1", "true", "yes", "on")

    _, merge_meta = merged_replay_rows()
    graded = int(merge_meta.get("total_graded") or 0)
    if graded < 5:
        return None

    if not force:
        if not weights_are_near_flat():
            return None
        current = load_weights()
        replayed = replay_weights_from_predictions()
        blended = soft_blend_weights(replayed, prior=dict(DEFAULT_WEIGHTS), replay_share=0.7)
        if all(abs(float(blended.get(name, 1.0)) - float(current.get(name, 1.0))) < 0.02 for name in DEFAULT_WEIGHTS):
            return None

    return rebalance_council_weights(save=True)


def save_weights(weights: Dict[str, float], path: Optional[str] = None) -> None:
    """Persist weights to adversarial_state.council_weights (canonical slot)
    AND mirror to root expert_weights for legacy compatibility."""
    path = path or SOUL_MAP_PATH
    data = _load_raw(path)
    adv = data.setdefault("adversarial_state", {})
    if not isinstance(adv, dict):
        adv = {}
        data["adversarial_state"] = adv
    canonical = normalize_council_weights(weights)
    adv["council_weights"] = {k: round(float(v), 4) for k, v in canonical.items()}
    adv["last_weight_update"] = _now_iso()
    # Mirror to root expert_weights so legacy readers always see learned values.
    data["expert_weights"] = {k: round(float(v), 4) for k, v in canonical.items()}
    _save_raw(data, path)


def nudge_expert(
    expert: Optional[str],
    correct: bool,
    path: Optional[str] = None,
    *,
    delta_correct: Optional[float] = None,
    delta_wrong: Optional[float] = None,
) -> Optional[float]:
    """Single nudge path for resolver + feedback (§27-4). Returns new weight."""
    if not expert:
        return None
    path = path or SOUL_MAP_PATH
    weights = load_weights(path)
    if expert not in weights:
        return None
    delta = (
        (delta_correct if delta_correct is not None else _LEARNING_DELTA_CORRECT)
        if correct
        else (delta_wrong if delta_wrong is not None else _LEARNING_DELTA_WRONG)
    )
    before = float(weights[expert])
    after = round(
        max(_LEARNING_MIN_WEIGHT, min(_LEARNING_MAX_WEIGHT, before + delta)),
        4,
    )
    weights[expert] = after
    save_weights(weights, path)
    return after


def detect_regime(market_data: Optional[Dict[str, Any]] = None) -> str:
    """Classify the market regime from aggregate market intelligence."""
    market_data = market_data or {}
    avg_change = float(market_data.get("avg_change_24h", 0) or 0)
    breadth = str(market_data.get("breadth", "neutral")).lower()
    volatility = float(market_data.get("volatility", 0) or 0)
    gainers = int(market_data.get("gainers", 0) or 0)
    losers = int(market_data.get("losers", 0) or 0)

    if volatility >= 8 or abs(avg_change) >= 8:
        return "high_volatility"
    if breadth == "bullish" or (gainers > losers * 1.5 and avg_change > 2):
        return "risk_on"
    if breadth == "bearish" or (losers > gainers * 1.5 and avg_change < -2):
        return "risk_off"
    return "chop"


def apply_regime_adjustment(
    weights: Dict[str, float], regime: str
) -> Dict[str, float]:
    """Apply regime multipliers to a weight dict (does not normalize)."""
    adj = learned_regime_adjustment(regime)
    adjusted = {}
    for name, w in weights.items():
        adjusted[name] = w * adj.get(name, 1.0)
    return adjusted


_MIN_REGIME_SAMPLES = 5
_SKIP_OUTCOMES = frozenset({"duplicate", "expired", "ungradeable"})


def _expert_hits_by_regime() -> Dict[str, Dict[str, List[bool]]]:
    """Map regime → expert → graded correct flags from resolved predictions."""
    out: Dict[str, Dict[str, List[bool]]] = {}
    try:
        from internal.learning.predictions_store import load_predictions

        data = load_predictions()
        for pred in data.get("resolved") or []:
            if not isinstance(pred, dict):
                continue
            if pred.get("outcome") in _SKIP_OUTCOMES:
                continue
            correct = pred.get("correct")
            if correct is None:
                continue
            raw = pred.get("expert")
            if not isinstance(raw, str) or not raw.strip():
                continue
            expert = raw.lower().strip()
            if expert == "contrarian":
                expert = "dark_horse"
            # Skip catch-all / unknown — do not bake into any expert's hit rate.
            if expert == "unclassified" or expert not in DEFAULT_WEIGHTS:
                continue
            snap = pred.get("subnet_snapshot") if isinstance(pred.get("subnet_snapshot"), dict) else {}
            regime = detect_regime(snap) if snap else "chop"
            out.setdefault(regime, {}).setdefault(expert, []).append(bool(correct))
    except Exception:
        pass
    return out


def learned_regime_adjustment(regime: str) -> Dict[str, float]:
    """Blend static REGIME_ADJUSTMENTS with per-expert hit rates in this regime (§21 L7)."""
    static = dict(REGIME_ADJUSTMENTS.get(regime, {}))
    hits = _expert_hits_by_regime().get(regime, {})
    acc: Dict[str, float] = {}
    for name, rows in hits.items():
        if len(rows) >= _MIN_REGIME_SAMPLES:
            acc[name] = sum(rows) / len(rows)
    if not acc:
        return static
    baseline = sum(acc.values()) / len(acc)
    learned: Dict[str, float] = {}
    for name in DEFAULT_WEIGHTS:
        static_m = static.get(name, 1.0)
        if name in acc:
            # ponytail: ±10% cap on learned nudge vs static regime table
            delta = max(-0.10, min(0.10, acc[name] - baseline))
            learned[name] = round(static_m * (1.0 + delta), 4)
        else:
            learned[name] = static_m
    return learned


def effective_weights(
    market_data: Optional[Dict[str, Any]] = None,
    path: str = SOUL_MAP_PATH,
) -> Dict[str, float]:
    """Load learned weights and apply regime adjustment without persisting."""
    base = load_weights(path)
    regime = detect_regime(market_data)
    return apply_regime_adjustment(base, regime)


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Signal weights (per-signal, per-horizon)
# ---------------------------------------------------------------------------


def load_signal_weights(path: str = SOUL_MAP_PATH) -> Dict[str, Dict[str, float]]:
    """Read learned signal weights from soul_map.json, defaulting to DEFAULT_SIGNAL_WEIGHTS."""
    data = _load_raw(path)
    adv = data.get("adversarial_state")
    if isinstance(adv, dict) and isinstance(adv.get("signal_weights"), dict):
        raw = adv["signal_weights"]
        signal_weights = dict(DEFAULT_SIGNAL_WEIGHTS)
        for horizon in ("hour", "day"):
            if isinstance(raw.get(horizon), dict):
                for signal_name, default_val in DEFAULT_SIGNAL_WEIGHTS[horizon].items():
                    signal_weights[horizon][signal_name] = float(raw[horizon].get(signal_name, default_val))
        return signal_weights
    return dict(DEFAULT_SIGNAL_WEIGHTS)


def save_signal_weights(
    signal_weights: Dict[str, Dict[str, float]],
    path: str = SOUL_MAP_PATH,
) -> None:
    """Persist signal weights to adversarial_state.signal_weights."""
    data = _load_raw(path)
    adv = data.setdefault("adversarial_state", {})
    if not isinstance(adv, dict):
        adv = {}
        data["adversarial_state"] = adv
    adv["signal_weights"] = {
        horizon: {k: round(float(v), 4) for k, v in weights.items()}
        for horizon, weights in signal_weights.items()
    }
    _save_raw(data, path)


def nudge_signal_weight(
    horizon_type: str,
    signal_name: str,
    correct: bool,
    path: str = SOUL_MAP_PATH,
) -> Optional[float]:
    """Nudge a single signal weight up (correct) or down (wrong), clamped to [0.1, 2.0]."""
    signal_weights = load_signal_weights(path)
    horizon_weights = signal_weights.setdefault(horizon_type, {})
    delta = _LEARNING_DELTA_CORRECT if correct else _LEARNING_DELTA_WRONG
    current = horizon_weights.get(signal_name, 1.0)
    before = float(current)
    new_val = max(_LEARNING_MIN_WEIGHT, min(_LEARNING_MAX_WEIGHT, current + delta))
    horizon_weights[signal_name] = round(new_val, 4)
    save_signal_weights(signal_weights, path)
    try:
        from internal.learning.trail_bus import emit_weight_change

        emit_weight_change(
            f"{horizon_type}:{signal_name}",
            before=before,
            after=float(new_val),
            reason="signal_resolve",
            correct=correct,
            extra={"horizon_type": horizon_type, "signal_name": signal_name},
        )
    except Exception:
        pass
    return float(new_val)


def load_impact_strength(path: Optional[str] = None) -> float:
    """Learned impact tilt from soul_map (default 1.0). Env IMPACT_STRENGTH overrides."""
    path = path or SOUL_MAP_PATH
    env = os.environ.get("IMPACT_STRENGTH")
    if env is not None and str(env).strip() != "":
        try:
            return max(_IMPACT_STRENGTH_MIN, min(_IMPACT_STRENGTH_MAX, float(env)))
        except (TypeError, ValueError):
            pass
    data = _load_raw(path)
    adv = data.get("adversarial_state")
    if isinstance(adv, dict) and adv.get("impact_strength") is not None:
        try:
            return max(
                _IMPACT_STRENGTH_MIN,
                min(_IMPACT_STRENGTH_MAX, float(adv["impact_strength"])),
            )
        except (TypeError, ValueError):
            pass
    return DEFAULT_IMPACT_STRENGTH


def save_impact_strength(strength: float, path: Optional[str] = None) -> float:
    """Persist impact_strength under adversarial_state for SimiVision learning."""
    path = path or SOUL_MAP_PATH
    clamped = max(_IMPACT_STRENGTH_MIN, min(_IMPACT_STRENGTH_MAX, float(strength)))
    data = _load_raw(path)
    adv = data.setdefault("adversarial_state", {})
    if not isinstance(adv, dict):
        adv = {}
        data["adversarial_state"] = adv
    adv["impact_strength"] = round(clamped, 4)
    adv["last_impact_strength_update"] = _now_iso()
    _save_raw(data, path)
    return clamped


def nudge_impact_strength(
    correct: bool,
    tier: Optional[str] = None,
    path: Optional[str] = None,
) -> float:
    """Nudge impact strength after a resolved pick.

    Small/mid correct → strengthen tilt (thin names deserved the edge).
    Small/mid wrong → weaken (over-correction toward micros).
    Large correct → weaken (large caps still work; tilt was too harsh).
    Large wrong → strengthen (should have dampened large caps more).

    No-op when IMPACT_STRENGTH env override is set (manual dial locked).
    """
    path = path or SOUL_MAP_PATH
    if os.environ.get("IMPACT_STRENGTH", "").strip() != "":
        return load_impact_strength(path)
    tier_l = str(tier or "").lower()
    current = load_impact_strength(path)
    if tier_l == "large":
        delta = -_IMPACT_STRENGTH_DELTA if correct else _IMPACT_STRENGTH_DELTA
    else:
        # small / mid / unknown
        delta = _IMPACT_STRENGTH_DELTA if correct else -_IMPACT_STRENGTH_DELTA
    return save_impact_strength(current + delta, path)


def compute_weighted_signal_score(
    signal_values: Dict[str, float],
    horizon_type: str,
    signal_weights: Dict[str, Dict[str, float]],
) -> float:
    """Compute weighted average of signal values using per-horizon signal weights."""
    horizon_weights = signal_weights.get(horizon_type, signal_weights.get("day", {}))
    weighted_sum = 0.0
    total_weight = 0.0
    for signal_name, value in signal_values.items():
        weight = horizon_weights.get(signal_name, 1.0)
        weighted_sum += value * weight
        total_weight += weight
    return round(weighted_sum / total_weight, 4) if total_weight > 0 else 0.5
