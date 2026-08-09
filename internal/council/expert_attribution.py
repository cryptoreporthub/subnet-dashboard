"""Council expert attribution — normalize, stamp, and measure (not weight nudge)."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

CANONICAL_EXPERTS = frozenset({"quant", "hype", "dark_horse", "technical"})

# Rogue bucket: rows that fail every attribution path land here (tracked,
# never scored, promotable to a real expert later).
ROGUE_EXPERT = "rogue"


def normalize_expert(prediction: Dict[str, Any]) -> Optional[str]:
    """Legacy lane normalizer for weight nudges — skips unclassified/unknown/neutral."""
    expert = prediction.get("expert") or prediction.get("signal_source")
    if not isinstance(expert, str):
        return None
    expert = expert.lower().strip()
    if not expert or expert in {"unclassified", "unknown", "neutral"}:
        return None

    if expert in CANONICAL_EXPERTS:
        return expert

    if expert in {"alpha"}:
        return "quant"
    if expert in {"beta"}:
        return "hype"
    if expert in {"gamma"}:
        return "dark_horse"

    if "contrarian" in expert or "dark" in expert or "horse" in expert or "onchain" in expert or "on-chain" in expert or "flow" in expert:
        return "dark_horse"
    if "whale" in expert or "momentum" in expert or "hype" in expert:
        return "hype"
    if "rsi" in expert or "macd" in expert or "technical" in expert:
        return "technical"
    if "quant" in expert or "fundamental" in expert or "yield" in expert:
        return "quant"

    return None


def _pick_blob_from_row(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for key in ("pick", "candidate"):
        blob = row.get(key)
        if isinstance(blob, dict):
            return blob
    if any(k in row for k in ("expert_contributions", "active_signals", "signal_impact")):
        return row
    return None


def _canonical_from_name(name: Any) -> Optional[str]:
    if not isinstance(name, str) or not name.strip():
        return None
    lowered = name.lower().strip()
    if lowered in CANONICAL_EXPERTS:
        return lowered
    return normalize_expert({"expert": name})


def resolve_expert_attribution(row: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """Return ``(canonical_expert, source_tag)`` for ledger stamping and measure."""
    existing = _canonical_from_name(row.get("expert"))
    if existing:
        return existing, "existing"

    from internal.council.signal_expert import expert_for_replay_row

    replayed = expert_for_replay_row(row)
    if replayed:
        return replayed, "replay"

    pick_blob = _pick_blob_from_row(row)
    if pick_blob is not None:
        from internal.council.expert_display import dominant_expert_for_learning

        leader = dominant_expert_for_learning(pick_blob)
        if leader in CANONICAL_EXPERTS:
            return leader, "pick_blend"

    normalized = normalize_expert(row)
    if normalized:
        return normalized, "normalize"

    return ROGUE_EXPERT, "unresolved"


def attribute_expert_for_row(row: Dict[str, Any]) -> Optional[str]:
    """Canonical council expert for measurement; ``None`` when unresolvable."""
    expert, _ = resolve_expert_attribution(row)
    return expert


def stamp_expert_on_row(row: Dict[str, Any]) -> bool:
    """Set ``expert`` + ``expert_attribution_source`` when attribution improves the row."""
    expert, source = resolve_expert_attribution(row)
    if not expert:
        return False
    current = _canonical_from_name(row.get("expert"))
    if current == expert and row.get("expert_attribution_source"):
        return False
    if current == expert and source == "existing":
        return False
    row["expert"] = expert
    if source != "existing":
        row["expert_attribution_source"] = source
    return True
