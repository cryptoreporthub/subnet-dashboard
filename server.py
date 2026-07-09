import json
import os

from flask import Flask, jsonify, render_template, request

from internal.council.mindmap_bridge import MindmapBridge

# Force rebuild - temporary comment for redeploy
app = Flask(__name__)

def load_data(filename):
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return json.load(f)
    return {}

def _load_subnets_source():
    """Return subnets for /api/subnets: live TaoMarketCap when available, else committed registry."""
    try:
        from fetchers.taomarketcap import get_all_subnets
        live = get_all_subnets()
        if live:
            return live
    except Exception:
        pass
    return list(load_data("config/registry.json").values())

def _consensus_map():
    """Build a subnet_id -> consensus decision lookup from the latest soul-map output."""
    soul_map = load_data("data/soul_map.json")
    last_output = soul_map.get("soul_map_state", {}).get("last_selector_output", {})
    decisions = last_output.get("decisions", [])
    return {d["subnet_id"]: d for d in decisions if "subnet_id" in d}

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
    return render_template("index.html")

@app.route("/api/daily-rotation", methods=["GET"])
def daily_rotation():
    """Return the latest daily rotation decisions plus live recommendations."""
    soul_map = load_data("data/soul_map.json")
    last_output = soul_map.get("soul_map_state", {}).get("last_selector_output", {})
    recommendations = MindmapBridge().get_brain_recommendations()
    return jsonify(
        {
            "status": "success",
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
    consensus = _consensus_map()
    # Enrich each entry with consensus data (additive, backward-compatible).
    enriched = {}
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
        enriched[key] = item
    return jsonify(enriched)

@app.route("/api/subnets", methods=["GET"])
def list_subnets():
    """List subnets with optional filtering, sorting, and pagination."""
    # Prefer LIVE TaoMarketCap data (real 24h/7d/30d); fall back to the committed registry.
    source = _load_subnets_source()
    items = []
    for s in source:
        item = dict(s)
        item.setdefault("id", s.get("netuid", 0))
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

    return jsonify({"status": "success", "meta": {"total": total, "limit": limit, "offset": offset}, "subnets": items})

@app.route("/api/subnet/<subnet_id>", methods=["GET"]) def get_subnet(subnet_id): data = load_data("config/registry.json") subnet_data = data.get(str(subnet_id)) if subnet_data is None: return jsonify({"error": "Subnet not found"}), 404 return jsonify({"subnet_id": subnet_id, "data": subnet_data}) @app.route("/api/summary", methods=["GET"]) def get_summary(): """Lightweight aggregated hero-card data for the dashboard.""" data = load_data("config/registry.json") subnets = list(data.values()) status_counts = {} total_stake = 0.0 total_emission = 0.0 total_mentions = 0 overvalued = 0 apys = [] last_updated = None for subnet in subnets: status = subnet.get("status", "unknown") status_counts[status] = status_counts.get(status, 0) + 1 total_stake += subnet.get("staking_data", {}).get("total_stake", 0.0) or 0.0 total_emission += subnet.get("emission", 0.0) or 0.0 total_mentions += subnet.get("social_mentions", 0) or 0 if subnet.get("is_overvalued"): overvalued += 1 apy = subnet.get("staking_data", {}).get("apy") if apy is not None: apys.append(apy) updated = subnet.get("last_updated") if updated and (last_updated is None or updated > last_updated): last_updated = updated # Featured highlights: top emitter, top staked, top APY, most mentioned. def top_by(field, n=1): def key(s): if field in ("total_stake", "apy"): return s.get("staking_data", {}).get(field, 0.0) or 0.0 return s.get(field, 0.0) or 0.0 ranked = sorted(subnets, key=key, reverse=True)[:n] return [ { "id": s.get("id"), "name": s.get("name"), "status": s.get("status"), field: key(s), } for s in ranked ] def top_by_consensus(n=1): ranked = sorted( subnets, key=lambda s: (s.get("consensus", {}) or {}).get("score", 0.0) or 0.0, reverse=True, )[:n] return [ { "id": s.get("id"), "name": s.get("name"), "status": s.get("status"), "consensus_score": (s.get("consensus", {}) or {}).get("score"), "recommended_action": (s.get("consensus", {}) or {}).get( "recommended_action" ), } for s in ranked ] def riskiest_by_consensus(n=1): flagged = [ s for s in subnets if s.get("status") in ("at-risk", "deprecated") or s.get("is_overvalued") ] ranked = sorted( flagged, key=lambda s: (s.get("consensus", {}) or {}).get("score", 1.0) or 1.0, )[:n] return [ { "id": s.get("id"), "name": s.get("name"), "status": s.get("status"), "consensus_score": (s.get("consensus", {}) or {}).get("score"), "recommended_action": (s.get("consensus", {}) or {}).get( "recommended_action" ), } for s in ranked ] total = len(subnets) or 1 status_distribution = { status: round(count / total, 4) for status, count in status_counts.items() } network_health = round(status_counts.get("active", 0) / total, 4) flagged_count = ( status_counts.get("at-risk", 0) + status_counts.get("deprecated", 0) + overvalued ) return jsonify( { "status": "success", "summary": { "total_subnets": len(subnets), "status_counts": status_counts, "status_distribution": status_distribution, "active_count": status_counts.get("active", 0), "at_risk_count": status_counts.get("at-risk", 0), "deprecated_count": status_counts.get("deprecated", 0), "unknown_count": status_counts.get("unknown", 0), "total_stake": round(total_stake, 4), "total_emission": round(total_emission, 4), "total_social_mentions": total_mentions, "overvalued_count": overvalued, "flagged_count": flagged_count, "avg_apy": round(sum(apys) / len(apys), 6) if apys else 0.0, "network_health": network_health, "last_updated": last_updated, }, "highlights": { "top_emitter": top_by("emission", 1), "top_staked": top_by("total_stake", 1), "top_apy": top_by("apy", 1), "most_mentioned": top_by("social_mentions", 1), "top_consensus": top_by_consensus(1), "riskiest": riskiest_by_consensus(1), }, } ) @app.route("/api/stats", methods=["GET"]) def get_stats(): """Aggregated registry intelligence for dashboard hero panels.""" data = load_data("config/registry.json") subnets = list(data.values()) status_counts = {} total_stake = 0.0 total_emission = 0.0 total_mentions = 0 overvalued = 0 apys = [] for subnet in subnets: status = subnet.get("status", "unknown") status_counts[status] = status_counts.get(status, 0) + 1 total_stake += subnet.get("staking_data", {}).get("total_stake", 0.0) or 0.0 total_emission += subnet.get("emission", 0.0) or 0.0 total_mentions += subnet.get("social_mentions", 0) or 0 if subnet.get("is_overvalued"): overvalued += 1 apy = subnet.get("staking_data", {}).get("apy") if apy is not None: apys.append(apy) def top_n(field, n=5): def key(s): value = s.get(field, 0) or 0 if field in ("total_stake", "apy"): value = s.get("staking_data", {}).get(field, 0) or 0 return value ranked = sorted(subnets, key=key, reverse=True)[:n] return [ { "id": s.get("id"), "name": s.get("name"), "status": s.get("status"), "emission": s.get("emission"), "total_stake": s.get("staking_data", {}).get("total_stake"), "apy": s.get("staking_data", {}).get("apy"), "social_mentions": s.get("social_mentions"), "is_overvalued": s.get("is_overvalued"), } for s in ranked ] flagged = [ { "id": s.get("id"), "name": s.get("name"), "status": s.get("status"), "risk_flags": s.get("risk_flags", []), "is_overvalued": s.get("is_overvalued"), "emission": s.get("emission"), } for s in subnets if s.get("status") in ("at-risk", "deprecated") or s.get("is_overvalued") ] return jsonify( { "status": "success", "summary": { "total_subnets": len(subnets), "status_counts": status_counts, "total_stake": round(total_stake, 4), "total_emission": round(total_emission, 4), "total_social_mentions": total_mentions, "overvalued_count": overvalued, "avg_apy": round(sum(apys) / len(apys), 6) if apys else 0.0, }, "top_emitters": top_n("emission"), "top_staked": top_n("total_stake"), "top_mentioned": top_n("social_mentions"), "flagged_subnets": flagged, } ) @app.route("/api/soul-map", methods=["GET"]) def get_soul_map(): """Expose the persisted Soul-Map state and feedback history.""" data = load_data("data/soul_map.json") return jsonify({"status": "success", "data": data}) @app.route("/api/recommendations", methods=["GET"]) def get_recommendations(): """Live Brain recommendations derived from the current registry.""" bridge = MindmapBridge() return jsonify({"status": "success", "data": bridge.get_brain_recommendations()}) @app.route("/api/mindmap/feedback", methods=["POST"]) def post_feedback(): feedback = request.get_json(silent=True) return jsonify({"status": "received", "feedback": feedback}) @app.route("/health", methods=["GET"]) def health(): return "OK" if __name__ == "__main__": port = int(os.environ.get("PORT", 50745)) app.run(host="0.0.0.0", port=port, debug=True)
