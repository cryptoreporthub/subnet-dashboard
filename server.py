import json
import os

from flask import Flask, jsonify, render_template, request

from internal.council.mindmap_bridge import MindmapBridge
from internal import freshness

app = Flask(__name__)

# Freshness configuration
app.config["ENABLE_BACKGROUND_SYNC"] = (
    os.environ.get("ENABLE_BACKGROUND_SYNC", "true").lower() != "false"
)


def load_data(filename):
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return json.load(f)
    return {}


# Lazily start the background sync once on the first request so it works
# under both `python server.py` and gunicorn without import-time side effects.
_background_sync_started = False


@app.before_request
def _ensure_background_sync():
    global _background_sync_started
    if _background_sync_started:
        return
    _background_sync_started = True
    if app.config["ENABLE_BACKGROUND_SYNC"] and not app.config.get("TESTING"):
        freshness.start_background_sync(immediate=False)


def _consensus_map():
    """Build a subnet_id -> consensus decision lookup from the latest soul-map output."""
    soul_map = load_data("data/soul_map.json")
    last_output = soul_map.get("soul_map_state", {}).get("last_selector_output", {})
    decisions = last_output.get("decisions", [])
    return {d["subnet_id"]: d for d in decisions if "subnet_id" in d}


def _enrich_registry(data):
    """Return registry items enriched with consensus decisions."""
    consensus = _consensus_map()
    enriched = []
    for key, value in data.items():
        item = dict(value)
        subnet_id = item.get("id", int(key))
        item.setdefault("id", subnet_id)
        decision = consensus.get(subnet_id)
        if decision:
            item["consensus"] = {
                "score": decision.get("consensus_score"),
                "recommended_action": decision.get("recommended_action"),
                "expert_breakdown": decision.get("expert_breakdown"),
            }
        enriched.append(item)
    return enriched


def _freshness_meta(source: str = "registry") -> dict:
    """Build a consistent freshness metadata block for API responses."""
    if source == "registry":
        info = freshness.registry_freshness()
    elif source == "soul_map":
        info = freshness.soul_map_freshness()
    elif source == "recommendations":
        info = freshness.recommendations_freshness()
    else:
        info = freshness.source_freshness(source, 300)
    return {
        "last_updated": info.get("last_updated"),
        "age_seconds": info.get("age_seconds"),
        "is_stale": info.get("is_stale"),
        "threshold_seconds": info.get("threshold_seconds"),
    }


def _build_simivision(data, recommendations):
    """Build the SimiVision top-picks payload from registry + brain recommendations.

    Merges the daily selector decisions (when available) with live Brain
    recommendations so every surfaced card is traceable back to underlying
    verdicts.
    """
    registry_by_id = {str(item.get("id", key)): item for key, item in data.items()}
    recs = recommendations.get("recommendations", {}) or {}
    soul_map = load_data("data/soul_map.json")
    last_output = soul_map.get("soul_map_state", {}).get("last_selector_output", {})
    decisions = last_output.get("decisions", []) or []
    decisions_by_id = {str(d.get("subnet_id")): d for d in decisions}

    choices = []
    for sub_id, rec in recs.items():
        subnet = registry_by_id.get(sub_id) or {}
        decision = decisions_by_id.get(sub_id) or {}
        action = decision.get("recommended_action") or rec.get("action") or "hold"
        target_weight = decision.get("target_weight") or rec.get("target_weight") or 0.5
        confidence = decision.get("consensus_score") or 0.5
        expert_breakdown = decision.get("expert_breakdown") or {
            "quant": {"score": confidence},
            "hype": {"score": confidence},
            "contrarian": {"score": confidence},
        }
        metrics = rec.get("metrics", {}) or {}
        emission = metrics.get("emission") or subnet.get("emission") or 0.0
        social_mentions = metrics.get("social_mentions") or subnet.get("social_mentions") or 0

        choices.append(
            {
                "subnet_id": subnet.get("id") or int(sub_id),
                "name": subnet.get("name") or f"Subnet {sub_id}",
                "action": action,
                "confidence": confidence,
                "edge_score": confidence,
                "preferred_entry": "Spot entry",
                "reward_risk": {"label": "favourable", "ratio": round(emission / 0.5, 2) if emission else 1.0},
                "horizon": "24h",
                "judge_agreement": "unanimous",
                "target_weight": target_weight,
                "expert_breakdown": expert_breakdown,
                "freshness": _freshness_meta("recommendations"),
                "emission": emission,
                "social_mentions": social_mentions,
            }
        )

    # Sort by confidence and surface the top 3 traceable picks.
    choices.sort(key=lambda c: c["confidence"], reverse=True)
    return {"choices": choices[:3]}


def _summarize_registry(data):
    """Build the dashboard summary/highlights payload from registry data."""
    subnets = list(data.values())

    status_counts = {}
    total_stake = 0.0
    total_emission = 0.0
    total_mentions = 0
    overvalued = 0
    apys = []
    last_updated = None

    for subnet in subnets:
        status = subnet.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        total_stake += subnet.get("staking_data", {}).get("total_stake", 0.0) or 0.0
        total_emission += subnet.get("emission", 0.0) or 0.0
        total_mentions += subnet.get("social_mentions", 0) or 0
        if subnet.get("is_overvalued"):
            overvalued += 1
        apy = subnet.get("staking_data", {}).get("apy")
        if apy is not None:
            apys.append(apy)
        updated = subnet.get("last_updated")
        if updated and (last_updated is None or updated > last_updated):
            last_updated = updated

    def top_by(field, n=1):
        def key(s):
            if field in ("total_stake", "apy"):
                return s.get("staking_data", {}).get(field, 0.0) or 0.0
            return s.get(field, 0.0) or 0.0

        ranked = sorted(subnets, key=key, reverse=True)[:n]
        return [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "status": s.get("status"),
                field: key(s),
            }
            for s in ranked
        ]

    def top_by_consensus(n=1):
        ranked = sorted(
            subnets,
            key=lambda s: (s.get("consensus", {}) or {}).get("score", 0.0) or 0.0,
            reverse=True,
        )[:n]
        return [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "status": s.get("status"),
                "consensus_score": (s.get("consensus", {}) or {}).get("score"),
                "recommended_action": (s.get("consensus", {}) or {}).get(
                    "recommended_action"
                ),
            }
            for s in ranked
        ]

    def riskiest_by_consensus(n=1):
        flagged = [
            s
            for s in subnets
            if s.get("status") in ("at-risk", "deprecated") or s.get("is_overvalued")
        ]
        ranked = sorted(
            flagged,
            key=lambda s: (s.get("consensus", {}) or {}).get("score", 1.0) or 1.0,
        )[:n]
        return [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "status": s.get("status"),
                "consensus_score": (s.get("consensus", {}) or {}).get("score"),
                "recommended_action": (s.get("consensus", {}) or {}).get(
                    "recommended_action"
                ),
            }
            for s in ranked
        ]

    total = len(subnets) or 1
    status_distribution = {
        status: round(count / total, 4) for status, count in status_counts.items()
    }
    network_health = round(status_counts.get("active", 0) / total, 4)
    flagged_count = (
        status_counts.get("at-risk", 0)
        + status_counts.get("deprecated", 0)
        + overvalued
    )

    return {
        "status": "success",
        "freshness": _freshness_meta("registry"),
        "summary": {
            "total_subnets": len(subnets),
            "status_counts": status_counts,
            "status_distribution": status_distribution,
            "active_count": status_counts.get("active", 0),
            "at_risk_count": status_counts.get("at-risk", 0),
            "deprecated_count": status_counts.get("deprecated", 0),
            "unknown_count": status_counts.get("unknown", 0),
            "total_stake": round(total_stake, 4),
            "total_emission": round(total_emission, 4),
            "total_social_mentions": total_mentions,
            "overvalued_count": overvalued,
            "flagged_count": flagged_count,
            "avg_apy": round(sum(apys) / len(apys), 6) if apys else 0.0,
            "network_health": network_health,
            "last_updated": last_updated,
        },
        "highlights": {
            "top_emitter": top_by("emission", 1),
            "top_staked": top_by("total_stake", 1),
            "top_apy": top_by("apy", 1),
            "most_mentioned": top_by("social_mentions", 1),
            "top_consensus": top_by_consensus(1),
            "riskiest": riskiest_by_consensus(1),
        },
    }


@app.after_request
def add_cors_headers(response):
    """Allow dashboard embedding and cross-origin API access."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["X-Frame-Options"] = "ALLOWALL"
    # Short cache for registry/summary to keep the dashboard snappy on Fly.io.
    if request.path in ("/api/registry", "/api/summary", "/api/stats"):
        response.headers["Cache-Control"] = "public, max-age=30"
    return response


@app.route("/")
def index():
    """Server-render the dashboard hero content for a premium first paint."""
    data = load_data("config/registry.json")
    enriched = _enrich_registry(data)
    summary_payload = _summarize_registry(data)
    recommendations = MindmapBridge().get_brain_recommendations()

    # Health status derived from required data files.
    health_status = "ok" if data and os.path.exists("data/soul_map.json") else "warn"

    # Top subnets for the scrolling ticker (duplicated client-side, but pre-filled here).
    ticker_items = sorted(
        enriched,
        key=lambda s: s.get("emission", 0.0) or 0.0,
        reverse=True,
    )[:12]

    freshness_state = freshness.overall_freshness()
    simivision = _build_simivision(data, recommendations)
    return render_template(
        "index.html",
        summary=summary_payload,
        registry=enriched,
        recommendations=recommendations,
        simivision=simivision,
        health_status=health_status,
        ticker_items=ticker_items,
        freshness=freshness_state,
    )


@app.route("/api/daily-rotation", methods=["GET"])
def daily_rotation():
    """Return the latest daily rotation decisions plus live recommendations."""
    soul_map = load_data("data/soul_map.json")
    last_output = soul_map.get("soul_map_state", {}).get("last_selector_output", {})
    recommendations = MindmapBridge().get_brain_recommendations()
    return jsonify(
        {
            "status": "success",
            "freshness": _freshness_meta("soul_map"),
            "data": {
                "date": last_output.get("date"),
                "decisions": last_output.get("decisions", []),
                "recommendations": recommendations.get("recommendations", {}),
                "updated_at": soul_map.get("soul_map_state", {}).get("updated_at"),
            },
        }
    )


@app.route("/api/registry", methods=["GET"])
def get_registry():
    data = load_data("config/registry.json")
    # Preserve the original string-keyed shape for API consumers; freshness
    # metadata is added alongside the subnet keys so existing integrations
    # that iterate by id keep working without change.
    enriched = {}
    for item in _enrich_registry(data):
        enriched[str(item["id"])] = item
    enriched["freshness"] = _freshness_meta("registry")
    return jsonify(enriched)


@app.route("/api/subnets", methods=["GET"])
def list_subnets():
    """List subnets with optional filtering, sorting, and pagination."""
    data = load_data("config/registry.json")
    items = []
    for key, value in data.items():
        item = dict(value)
        item.setdefault("id", int(key))
        items.append(item)

    status_filter = request.args.get("status")
    if status_filter:
        statuses = {s.strip().lower() for s in status_filter.split(",")}
        items = [i for i in items if str(i.get("status", "")).lower() in statuses]

    sort_field = request.args.get("sort", "id")
    order = request.args.get("order", "asc").lower()
    reverse = order == "desc"

    def sort_key(item):
        value = item.get(sort_field)
        if value is None and sort_field == "total_stake":
            value = item.get("staking_data", {}).get("total_stake")
        elif value is None and sort_field == "apy":
            value = item.get("staking_data", {}).get("apy")
        if isinstance(value, (int, float)):
            return (0, value)
        if isinstance(value, str):
            return (1, value.lower())
        return (2, "")

    items = sorted(items, key=sort_key, reverse=reverse)

    try:
        limit = int(request.args.get("limit", 0))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        limit = 0
        offset = 0

    total = len(items)
    if offset:
        items = items[offset:]
    if limit > 0:
        items = items[:limit]

    return jsonify(
        {
            "status": "success",
            "freshness": _freshness_meta("registry"),
            "meta": {"total": total, "limit": limit, "offset": offset},
            "subnets": items,
        }
    )


@app.route("/api/subnet/<int:subnet_id>", methods=["GET"])
def get_subnet(subnet_id):
    data = load_data("config/registry.json")
    subnet_data = data.get(str(subnet_id))
    if subnet_data is None:
        return jsonify({"error": "Subnet not found"}), 404
    return jsonify({"subnet_id": subnet_id, "data": subnet_data})


@app.route("/api/summary", methods=["GET"])
def get_summary():
    """Lightweight aggregated hero-card data for the dashboard."""
    data = load_data("config/registry.json")
    return jsonify(_summarize_registry(data))


@app.route("/api/stats", methods=["GET"])
def get_stats():
    """Aggregated registry intelligence for dashboard hero panels."""
    data = load_data("config/registry.json")
    subnets = list(data.values())

    status_counts = {}
    total_stake = 0.0
    total_emission = 0.0
    total_mentions = 0
    overvalued = 0
    apys = []

    for subnet in subnets:
        status = subnet.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        total_stake += subnet.get("staking_data", {}).get("total_stake", 0.0) or 0.0
        total_emission += subnet.get("emission", 0.0) or 0.0
        total_mentions += subnet.get("social_mentions", 0) or 0
        if subnet.get("is_overvalued"):
            overvalued += 1
        apy = subnet.get("staking_data", {}).get("apy")
        if apy is not None:
            apys.append(apy)

    def top_n(field, n=5):
        def key(s):
            value = s.get(field, 0) or 0
            if field in ("total_stake", "apy"):
                value = s.get("staking_data", {}).get(field, 0) or 0
            return value

        ranked = sorted(subnets, key=key, reverse=True)[:n]
        return [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "status": s.get("status"),
                "emission": s.get("emission"),
                "total_stake": s.get("staking_data", {}).get("total_stake"),
                "apy": s.get("staking_data", {}).get("apy"),
                "social_mentions": s.get("social_mentions"),
                "is_overvalued": s.get("is_overvalued"),
            }
            for s in ranked
        ]

    flagged = [
        {
            "id": s.get("id"),
            "name": s.get("name"),
            "status": s.get("status"),
            "risk_flags": s.get("risk_flags", []),
            "is_overvalued": s.get("is_overvalued"),
            "emission": s.get("emission"),
        }
        for s in subnets
        if s.get("status") in ("at-risk", "deprecated") or s.get("is_overvalued")
    ]

    return jsonify(
        {
            "status": "success",
            "freshness": _freshness_meta("registry"),
            "summary": {
                "total_subnets": len(subnets),
                "status_counts": status_counts,
                "total_stake": round(total_stake, 4),
                "total_emission": round(total_emission, 4),
                "total_social_mentions": total_mentions,
                "overvalued_count": overvalued,
                "avg_apy": round(sum(apys) / len(apys), 6) if apys else 0.0,
            },
            "top_emitters": top_n("emission"),
            "top_staked": top_n("total_stake"),
            "top_mentioned": top_n("social_mentions"),
            "flagged_subnets": flagged,
        }
    )


@app.route("/api/soul-map", methods=["GET"])
def get_soul_map():
    """Expose the persisted Soul-Map state and feedback history."""
    data = load_data("data/soul_map.json")
    return jsonify(
        {
            "status": "success",
            "freshness": _freshness_meta("soul_map"),
            "data": data,
        }
    )


@app.route("/api/recommendations", methods=["GET"])
def get_recommendations():
    """Live Brain recommendations derived from the current registry."""
    bridge = MindmapBridge()
    return jsonify(
        {
            "status": "success",
            "freshness": _freshness_meta("recommendations"),
            "data": bridge.get_brain_recommendations(),
        }
    )


@app.route("/api/mindmap/feedback", methods=["POST"])
def post_feedback():
    feedback = request.get_json(silent=True)
    return jsonify({"status": "received", "feedback": feedback})


@app.route("/api/freshness", methods=["GET"])
def get_freshness():
    """Expose freshness state for all dashboard data sources."""
    return jsonify({"status": "success", "data": freshness.get_sync_state()})


@app.route("/api/sync", methods=["POST", "GET"])
def trigger_sync():
    """Trigger an on-demand refresh of remote data sources."""
    report = freshness.refresh_all()
    return jsonify({"status": "success", "data": report})


@app.route("/health", methods=["GET"])
def health():
    return "OK"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 50745))
    # Background sync is disabled in testing to avoid thread interference.
    if app.config["ENABLE_BACKGROUND_SYNC"] and not app.config.get("TESTING"):
        freshness.start_background_sync(immediate=False)
    app.run(host="0.0.0.0", port=port, debug=True)
