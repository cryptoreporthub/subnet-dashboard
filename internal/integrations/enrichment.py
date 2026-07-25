"""Evidence drivers from optional subnet integrations (DeSearch, Synth)."""

from __future__ import annotations

from typing import Any, Dict, List

from internal.integrations import clients


def integration_evidence_drivers(netuid: int, name: str = "") -> List[Dict[str, str]]:
    """Up to two tagged drivers from SN22/SN50 when API keys are configured."""
    out: List[Dict[str, str]] = []

    snippet = clients.desearch_subnet_snippet(netuid, name=name)
    if snippet:
        out.append({"tag": "social", "label": f"DeSearch · {snippet[:56]}"})

    macro = clients.synth_macro_skew()
    if macro:
        pct = macro.get("median_pct")
        asset = macro.get("asset", "BTC")
        horizon = macro.get("horizon", "24h")
        direction = macro.get("direction", "flat")
        out.append(
            {
                "tag": "tech",
                "label": f"Synth {asset} {horizon} {direction} ({pct:+.1f}% med)",
            }
        )

    return out[:2]
