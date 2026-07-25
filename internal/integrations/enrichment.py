"""Evidence drivers from optional subnet integrations (DeSearch)."""

from __future__ import annotations

from typing import Any, Dict, List

from internal.integrations import clients


def integration_evidence_drivers(netuid: int, name: str = "") -> List[Dict[str, str]]:
    """Up to one tagged driver from SN22 when the API key is configured."""
    out: List[Dict[str, str]] = []

    snippet = clients.desearch_subnet_snippet(netuid, name=name)
    if snippet:
        out.append({"tag": "social", "label": f"DeSearch · {snippet[:56]}"})

    return out[:1]
