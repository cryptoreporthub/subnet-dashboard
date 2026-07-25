"""DeSearch HTTP helper — auth + billing header capture."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from internal.integrations.desearch_spend import record_desearch_response


def desearch_api_key() -> Optional[str]:
    return os.environ.get("DESEARCH_API_KEY") or os.environ.get("DESEARCH_ACCESS_KEY")


def desearch_base_url() -> str:
    return os.environ.get("DESEARCH_BASE_URL", "https://api.desearch.ai").rstrip("/")


def desearch_auth_headers(api_key: Optional[str] = None) -> Dict[str, str]:
    key = api_key or desearch_api_key()
    if not key:
        return {}
    # SDK + OpenAPI: Authorization without Bearer; legacy paths accept access-key.
    return {
        "Authorization": key,
        "access-key": key,
        "Content-Type": "application/json",
    }


def desearch_request(
    method: str,
    path: str,
    *,
    json_body: Optional[Dict[str, Any]] = None,
    timeout: int = 12,
    label: str = "",
):
    """HTTP call to DeSearch; records X-Desearch-* billing headers when present."""
    import requests

    base = desearch_base_url()
    url = path if path.startswith("http") else f"{base}/{path.lstrip('/')}"
    headers = desearch_auth_headers()
    resp = requests.request(
        method,
        url,
        headers=headers,
        json=json_body,
        timeout=timeout,
    )
    record_desearch_response(resp, path=path, label=label)
    return resp
