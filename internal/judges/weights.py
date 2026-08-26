"""Per-judge (Oracle/Echo/Pulse) confidence weights.

Closes the judges learning loop: each judge's selective endorsement grade
(score gate vs council outcome) nudges its own weight, read back into the
consensus blend in subnet_judges.py.
"""

import os
from typing import Any, Dict, Optional

SOUL_MAP_PATH = os.path.join("data", "soul_map.json")

DEFAULT_JUDGE_WEIGHTS: Dict[str, float] = {
    "oracle": 0.35,
    "echo": 0.30,
    "pulse": 0.35,
}

# Symmetric steps — asymmetric +0.02/−0.03 required ~60% win rate just to stay
# flat and collapsed all three judges to the floor (equal 33% after normalize).
# See docs/sciweave-answers-phase-j.md Q5.
_LEARNING_DELTA_CORRECT = 0.02
_LEARNING_DELTA_WRONG = -0.02
_LEARNING_MIN_WEIGHT = 0.1
_LEARNING_MAX_WEIGHT = 2.0


def normalize_judge_weights(raw: Any) -> Dict[str, float]:
    out = dict(DEFAULT_JUDGE_WEIGHTS)
    if not isinstance(raw, dict):
        return out
    for key in DEFAULT_JUDGE_WEIGHTS:
        if key in raw:
            try:
                out[key] = float(raw[key])
            except (TypeError, ValueError):
                pass
    return out


def load_judge_weights(path: Optional[str] = None) -> Dict[str, float]:
    from internal.store.soul_map_io import read_soul_map

    resolved = path or SOUL_MAP_PATH
    data = read_soul_map(resolved)
    return normalize_judge_weights(data.get("judge_weights"))


def save_judge_weights(weights: Dict[str, float], path: Optional[str] = None) -> None:
    from internal.store.soul_map_io import write_soul_map

    canonical = normalize_judge_weights(weights)
    rounded = {k: round(float(v), 4) for k, v in canonical.items()}

    def _mutate(blob: Dict[str, Any]) -> None:
        blob["judge_weights"] = rounded

    write_soul_map(_mutate, path=path or SOUL_MAP_PATH)


def nudge_judge(
    judge_name: Optional[str],
    correct: bool,
    path: Optional[str] = None,
    *,
    delta_correct: Optional[float] = None,
    delta_wrong: Optional[float] = None,
    scale: float = 1.0,
    actual_pct: Optional[float] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Optional[float]:
    if not judge_name or judge_name not in DEFAULT_JUDGE_WEIGHTS:
        return None
    resolved_path = path or SOUL_MAP_PATH
    weights = load_judge_weights(resolved_path)
    move_scale = max(0.0, float(scale))
    base = (
        (delta_correct if delta_correct is not None else _LEARNING_DELTA_CORRECT)
        if correct
        else (delta_wrong if delta_wrong is not None else _LEARNING_DELTA_WRONG)
    )
    delta = round(base * move_scale, 4)
    before = float(weights[judge_name])
    after = round(
        max(_LEARNING_MIN_WEIGHT, min(_LEARNING_MAX_WEIGHT, before + delta)),
        4,
    )
    weights[judge_name] = after
    save_judge_weights(weights, resolved_path)
    if after != before:
        try:
            from internal.learning.trail_bus import emit_weight_change

            emit_weight_change(
                judge_name,
                before=before,
                after=after,
                reason="judge_pnl",
                correct=correct,
                extra={
                    "scale": move_scale,
                    "actual_pct": actual_pct,
                    **(extra or {}),
                },
            )
        except Exception:
            pass
    return after


def normalized_judge_weights(path: Optional[str] = None) -> Dict[str, float]:
    weights = load_judge_weights(path)
    total = sum(weights.values())
    if not total or total <= 0:
        return dict(DEFAULT_JUDGE_WEIGHTS)
    return {k: v / total for k, v in weights.items()}
