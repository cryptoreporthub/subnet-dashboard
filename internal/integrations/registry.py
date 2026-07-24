"""Bittensor subnet integration catalog (TaonSquare + Ditto research)."""

from __future__ import annotations

from typing import Any, Dict, List

# ponytail: static rows; probe logic lives in status.py
INTEGRATIONS: List[Dict[str, Any]] = [
    {
        "netuid": 118,
        "slug": "ditto",
        "name": "Ditto",
        "role": "Agent memory (SN118)",
        "docs_url": "https://heyditto.ai",
        "tier": "core",
    },
    {
        "netuid": 64,
        "slug": "chutes",
        "name": "Chutes",
        "role": "Council LLM compute",
        "docs_url": "https://docs.chutes.ai",
        "tier": "core",
    },
    {
        "netuid": 50,
        "slug": "synth",
        "name": "Synth",
        "role": "Macro forecasting signals",
        "docs_url": "https://api.synthdata.co/docs",
        "tier": "core",
    },
    {
        "netuid": 22,
        "slug": "desearch",
        "name": "DeSearch",
        "role": "Search & social evidence",
        "docs_url": "https://www.desearch.ai/docs/api-reference",
        "tier": "core",
    },
    {
        "netuid": 6,
        "slug": "numinous",
        "name": "Numinous",
        "role": "Forecasting protocol",
        "docs_url": "https://eversight.numinouslabs.io/docs/eversight",
        "tier": "extended",
    },
    {
        "netuid": 13,
        "slug": "data_universe",
        "name": "Data Universe",
        "role": "Social data pipeline",
        "docs_url": "https://docs.macrocosmos.ai/subnets/subnet-13-data-universe",
        "tier": "extended",
    },
    {
        "netuid": 8,
        "slug": "vanta",
        "name": "Vanta",
        "role": "Trading signal network",
        "docs_url": "https://docs.taoshi.io",
        "tier": "extended",
    },
    {
        "netuid": 33,
        "slug": "readyai",
        "name": "ReadyAI",
        "role": "Structured domain intel",
        "docs_url": "https://readyai.ai/docs",
        "tier": "extended",
    },
    {
        "netuid": 51,
        "slug": "lium",
        "name": "Lium",
        "role": "GPU compute marketplace",
        "docs_url": "https://docs.lium.io",
        "tier": "extended",
    },
    {
        "netuid": 43,
        "slug": "graphite",
        "name": "Graphite",
        "role": "Copy-trading finance",
        "docs_url": "https://github.com/GraphiteAI/Graphite-Subnet",
        "tier": "extended",
    },
    {
        "netuid": 45,
        "slug": "talisman",
        "name": "Talisman AI",
        "role": "Financial perception layer",
        "docs_url": "https://taonsquare.com",
        "tier": "extended",
    },
]

INTEGRATION_NETUIDS = {row["netuid"] for row in INTEGRATIONS}
