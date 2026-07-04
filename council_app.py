"""Thin wrapper around server:app that adds the /api/council route.
This file is the uvicorn entry point (Dockerfile/Procfile CMD).
It imports the full app from server.py and appends one route.""""

from datetime import datetime

from server import app  # noqa: F401  -- re-exported for uvicorn


@app.get("/api/council")
async def api_council():
    """Serve the complete merged data pipeline with judge scores."""
    try:
        # Try merged data pipeline first, fall back to taomarketcap
        try:
            from fetchers.merged_data import get_merged_subnet_data
            merged = get_merged_subnet_data()
            source = "merged"
        except Exception:
            from fetchers.taomarketcap import get_all_subnets
            data = get_all_subnets()
            merged = data if isinstance(data, list) else (data.get("subnets", []) if isinstance(data, dict) else [])
            source = "taomarketcap"

        if not merged:
            return {"status": "degraded", "subnets": [], "judges": [], "meta": {"count": 0, "judged": 0, "source": source}}

        try:
            from internal.judges.subnet_judges import score_all_subnets
            scored = score_all_subnets(merged)
        except Exception:
            scored = []

        return {
            "status": "success",
            "subnets": merged,
            "judges": scored,
            "meta": {
                "count": len(merged),
                "judged": len(scored) if scored else 0,
                "source": source,
                "updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "subnets": [], "judges": []}
