"""
Self-learning bridge between AdversarialJudge verdicts and indicator thresholds.

Reads recent verdicts persisted by the adversarial layer in the Soul-Map and
adjusts indicator sensitivity. The tuned thresholds are consumed by the
IndicatorEngine on the next refresh.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict

SOUL_MAP_PATH = os.environ.get("SOUL_MAP_PATH", "data/soul_map.json")
INDICATOR_STATE_PATH = os.environ.get("INDICATOR_STATE_PATH", "data/indicator_state.json")

DEFAULT_THRESHOLDS: Dict[str, float] = {
    "rsi_oversold": 30.0,
    "rsi_overbought": 70.0,
    "momentum_threshold": 3.0,
    "conviction_floor": 30.0,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_json(path: str, data: Dict[str, Any]) -> None:
    dir_name = os.path.dirname(path)
    if dir_name and not os.path.exists(dir_name):
        os.makedirs(dir_name, exist_ok=True)
    temp_path = path + ".tmp"
    with open(temp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_path, path)


def load_thresholds() -> Dict[str, float]:
    """Return the current tuned thresholds, falling back to defaults."""
    state = _load_json(INDICATOR_STATE_PATH)
    thresholds = dict(DEFAULT_THRESHOLDS)
    thresholds.update(state.get("thresholds", {}))
    return thresholds


def tune_thresholds_from_verdicts(
    verdict_limit: int = 200,
    min_samples: int = 5,
) -> Dict[str, float]:
    """Tune indicator thresholds using recent AdversarialJudge verdicts.

    Logic:
    - If "accumulate" actions are repeatedly validated, lower the RSI oversold
      floor (making mean-reversion buy signals slightly easier to trigger).
    - If "accumulate" actions are repeatedly contradicted, raise it.
    - If "reduce" actions are validated, raise the overbought ceiling.
    - Contradicted reduces lower it.

    Returns:
        Updated threshold dict and writes it to the indicator state file.
    """
    data = _load_json(SOUL_MAP_PATH)
    verdicts = data.get("adversarial_state", {}).get("verdicts", [])
    if not verdicts:
        return load_thresholds()

    recent = verdicts[-verdict_limit:]
    accumulate_validated = sum(
        1
        for v in recent
        if v.get("action") == "accumulate" and v.get("outcome_label") == "validated"
    )
    accumulate_contradicted = sum(
        1
        for v in recent
        if v.get("action") == "accumulate" and v.get("outcome_label") == "contradicted"
    )
    reduce_validated = sum(
        1
        for v in recent
        if v.get("action") == "reduce" and v.get("outcome_label") == "validated"
    )
    reduce_contradicted = sum(
        1
        for v in recent
        if v.get("action") == "reduce" and v.get("outcome_label") == "contradicted"
    )

    thresholds = load_thresholds()
    step = 1.0

    if accumulate_validated >= min_samples and accumulate_validated > accumulate_contradicted:
        thresholds["rsi_oversold"] = max(20.0, thresholds["rsi_oversold"] - step)
    elif accumulate_contradicted >= min_samples and accumulate_contradicted > accumulate_validated:
        thresholds["rsi_oversold"] = min(40.0, thresholds["rsi_oversold"] + step)

    if reduce_validated >= min_samples and reduce_validated > reduce_contradicted:
        thresholds["rsi_overbought"] = min(80.0, thresholds["rsi_overbought"] + step)
    elif reduce_contradicted >= min_samples and reduce_contradicted > reduce_validated:
        thresholds["rsi_overbought"] = max(60.0, thresholds["rsi_overbought"] - step)

    # Small momentum-threshold drift toward whichever direction has been validated.
    net_momentum = (
        accumulate_validated + reduce_validated
    ) - (accumulate_contradicted + reduce_contradicted)
    if abs(net_momentum) >= min_samples:
        thresholds["momentum_threshold"] = max(
            1.0, min(8.0, thresholds["momentum_threshold"] - (0.2 * (net_momentum / abs(net_momentum))))
        )

    state = _load_json(INDICATOR_STATE_PATH)
    state["thresholds"] = thresholds
    state["threshold_tuned_at"] = _now_iso()
    state["tuning_stats"] = {
        "accumulate_validated": accumulate_validated,
        "accumulate_contradicted": accumulate_contradicted,
        "reduce_validated": reduce_validated,
        "reduce_contradicted": reduce_contradicted,
    }
    _save_json(INDICATOR_STATE_PATH, state)
    return thresholds
