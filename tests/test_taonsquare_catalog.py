"""TaonSquare catalog scoring for subnet integration candidates."""

from __future__ import annotations

from unittest.mock import patch

from internal.integrations.registry import INTEGRATION_NETUIDS
from internal.integrations.taonsquare import recommend_candidates


_MOCK_CATALOG = [
    {
        "netuid": 6,
        "name": "Numinous",
        "status": "live",
        "category": "Predictive Systems",
        "description": "forecasting protocol aggregating AI agents",
        "tags": ["prediction", "forecast"],
        "api_available": True,
        "api_url": None,
        "docs_url": None,
        "website_url": "https://numinous.ai",
        "pricing_model": "open-source",
        "market_cap_tao": 1000,
        "source": "taonsquare",
    },
    {
        "netuid": 13,
        "name": "Data Universe",
        "status": "live",
        "category": "Data Pipeline",
        "description": "social media data from X Twitter",
        "tags": ["social", "data"],
        "api_available": True,
        "api_url": "https://example.com/gravity",
        "docs_url": "https://github.com/macrocosm-os/data-universe",
        "website_url": None,
        "pricing_model": "free",
        "market_cap_tao": 500,
        "source": "taonsquare",
    },
    {
        "netuid": 99,
        "name": "No API Subnet",
        "status": "live",
        "category": "Other",
        "description": "no public api",
        "tags": [],
        "api_available": False,
        "api_url": None,
        "docs_url": None,
        "website_url": None,
        "pricing_model": None,
        "market_cap_tao": None,
        "source": "taonsquare",
    },
]


def test_recommend_candidates_excludes_primary_and_ranks_forecast():
    with patch("internal.integrations.taonsquare.fetch_catalog", return_value=_MOCK_CATALOG):
        rows = recommend_candidates(exclude=INTEGRATION_NETUIDS, limit=5)
    netuids = [r["netuid"] for r in rows]
    assert 99 not in netuids
    assert 6 not in netuids  # now in INTEGRATIONS registry
    assert rows == [] or rows[0]["tier"] == "candidate"


def test_integrations_api_includes_taonsquare_candidates():
    from fastapi.testclient import TestClient

    from server import app

    extra_candidate = {
        "netuid": 77,
        "name": "FutureSubnet",
        "status": "live",
        "category": "Predictive Systems",
        "description": "forecast market analytics",
        "tags": ["forecast", "prediction"],
        "api_available": True,
        "api_url": "https://example.com",
        "docs_url": None,
        "website_url": None,
        "pricing_model": None,
        "market_cap_tao": None,
        "source": "taonsquare",
    }
    mock_catalog = _MOCK_CATALOG + [extra_candidate]
    with patch("internal.integrations.taonsquare.fetch_catalog", return_value=mock_catalog):
        with TestClient(app) as client:
            body = client.get("/api/subnet-integrations").json()
    assert "candidates" in body
    assert "catalog" in body
    assert body["catalog"]["source"] == "taonsquare.com"
    cand_uids = {c["netuid"] for c in body["candidates"]}
    assert 22 not in cand_uids
    assert 6 not in cand_uids
    assert 77 in cand_uids
