"""Plain-language summary for the Scenario Memory panel (Phase B)."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional


def summarize_scenario(scenario_state: Optional[Dict[str, Any]] = None) -> str:
    """Return 3–4 sentences describing live scenario memory.

    Accepts the dict returned by ``load_scenario_snapshot`` or GET
    ``/api/scenario-memory`` (``scenarios``, ``stats``, ``meta`` keys).
    """
    state = scenario_state or {}
    scenarios: List[Dict[str, Any]] = state.get("scenarios") or []
    stats = state.get("stats") or {}
    meta = state.get("meta") or {}

    if not scenarios:
        return (
            "Scenario memory is empty — no regime-tagged snapshots have been recorded yet. "
            "When Council picks or the resolver grades predictions, tagged scenarios will "
            "appear here with regime, RSI bucket, and volume profile. "
            "Trail events will fire as each snapshot is written."
        )

    total = int(stats.get("total") or len(scenarios))
    by_regime: Dict[str, int] = stats.get("by_regime") or {}
    dominant_regime = max(by_regime, key=by_regime.get, default="neutral") if by_regime else "neutral"
    dominant_count = by_regime.get(dominant_regime, 0)

    latest = scenarios[-1]
    features = latest.get("features") or {}
    regime = latest.get("regime") or dominant_regime
    rsi = features.get("rsi") or features.get("rsi_bucket") or "unknown"
    volume = features.get("volume") or features.get("vol_profile") or "unknown"
    volatility = features.get("volatility")
    vol_label = _vol_profile(volatility, features)

    tag_counter: Counter[str] = Counter()
    for sc in scenarios[-20:]:
        feats = sc.get("features") or {}
        for key in ("direction", "expert", "outcome"):
            val = feats.get(key)
            if val:
                tag_counter[str(val)] += 1
        tags = feats.get("tags")
        if isinstance(tags, list):
            tag_counter.update(str(t) for t in tags)
        elif isinstance(tags, dict):
            for k, v in tags.items():
                tag_counter[f"{k}:{v}"] += 1

    notable_tags = [f"{tag} ({count})" for tag, count in tag_counter.most_common(4)]
    tags_text = ", ".join(notable_tags) if notable_tags else "no dominant tags yet"

    accuracy = stats.get("accuracy") or {}
    acc_bits = [
        f"{reg} {int(pct * 100)}%"
        for reg, pct in sorted(accuracy.items())
        if pct is not None
    ]
    acc_text = f" Resolved accuracy by regime: {', '.join(acc_bits)}." if acc_bits else ""

    last_updated = meta.get("last_updated", "recently")
    latest_name = latest.get("name", "unknown subnet")

    return (
        f"Scenario memory holds {total} tagged snapshots; the prevailing regime is "
        f"{dominant_regime} ({dominant_count} records). "
        f"The latest entry for {latest_name} is tagged {regime} with RSI in the "
        f"{rsi} bucket and {vol_label} volume profile (vol score {volume}). "
        f"Recent notable tags: {tags_text}.{acc_text} "
        f"Last disk update: {last_updated}."
    )


def _vol_profile(volatility: Any, features: Dict[str, Any]) -> str:
    if volatility is not None:
        try:
            v = float(volatility)
            if v >= 15:
                return "high-volatility"
            if v >= 8:
                return "elevated"
            if v >= 3:
                return "moderate"
            return "low-volatility"
        except (TypeError, ValueError):
            pass
    breadth = str(features.get("breadth", "")).lower()
    if breadth in {"volatile", "high"}:
        return "high-volatility"
    return str(features.get("vol_profile") or "moderate")
