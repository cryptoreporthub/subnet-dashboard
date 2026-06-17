import json
import os
from datetime import datetime

from flask import Flask, jsonify, render_template, request

from internal.council.mindmap_bridge import MindmapBridge
from internal.council.judge.adversarial import AdversarialJudge
from internal import freshness

app = Flask(__name__)

# Protocol watchlist configuration: first-class scan targets surfaced in the UI.
_PROTOCOLS_PATH = os.environ.get("PROTOCOLS_PATH", "config/protocols.json")
_protocols_config = {}


def _load_protocols_config():
    """Load the protocol watchlist mapping once at startup."""
    global _protocols_config
    if _protocols_config:
        return _protocols_config
    if os.path.exists(_PROTOCOLS_PATH):
        try:
            with open(_PROTOCOLS_PATH, "r") as f:
                data = json.load(f)
            _protocols_config = data.get("watchlist", {})
        except Exception:
            _protocols_config = {}
    return _protocols_config


def _protocol_tag_for(name):
    """Return the first matching protocol label for a subnet name, or None."""
    if not name:
        return None
    lowered = name.lower()
    for key, cfg in _load_protocols_config().items():
        for pattern in cfg.get("patterns", []):
            if pattern.lower() in lowered:
                return cfg.get("label", key)
    return None

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
    """Return registry items enriched with consensus decisions and protocol tags."""
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
        # Surface first-class protocol watchlist tags for the scan pipeline.
        protocol_tag = _protocol_tag_for(item.get("name", ""))
        if protocol_tag:
            item["protocol_tag"] = protocol_tag
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
    elif source == "watchlist":
        info = freshness.watchlist_freshness()
    else:
        info = freshness.source_freshness(source, 300)
    return {
        "last_updated": info.get("last_updated"),
        "age_seconds": info.get("age_seconds"),
        "is_stale": info.get("is_stale"),
        "threshold_seconds": info.get("threshold_seconds"),
    }


def _load_watchlist() -> dict:
    """Load the protocol watchlist config and attach a UI protocol tag."""
    data = load_data(freshness.WATCHLIST_PATH)
    protocols = data.get("protocols", {})
    # Map watchlist symbols to the canonical protocol labels used by the
    # scan pipeline and the futuristic badge styling.
    symbol_to_label = {
        "VVV": "VVV",
        "FET": "Fetch",
        "RENDER": "Render",
        "TAO": "Tao",
        "HYPE": "Hyperliquid",
    }
    return {
        "last_updated": data.get("last_updated"),
        "protocols": [
            {
                "symbol": symbol,
                "protocol_tag": symbol_to_label.get(symbol),
                **info,
            }
            for symbol, info in protocols.items()
        ],
    }


def _synthesize_decisions(registry, recommendations):
    """Generate traceable fallback decisions when the Selector has not yet run.
    Scores are derived from registry metrics and Brain recommendations so the
    SimiVision panel never surfaces placeholder picks.
    """
    recs = recommendations.get("recommendations", {})
    decisions = []
    for key, item in registry.items():
        subnet_id = item.get("id", int(key))
        status = item.get("status", "unknown")
        emission = item.get("emission", 0.0) or 0.0
        mentions = item.get("social_mentions", 0) or 0
        is_overvalued = item.get("is_overvalued", False)
        brain_rec = recs.get(str(subnet_id), {})
        brain_action = brain_rec.get("action", "hold")

        # Synthetic expert scores mirror the live expert heuristics.
        quant_score = 0.85 if emission > 1.0 else 0.4 if emission < 0.2 else 0.75
        hype_score = 0.9 if mentions > 1000 else 0.3 if mentions < 100 else 0.65
        contrarian_score = 0.2 if is_overvalued else 0.8

        if brain_action == "accumulate":
            consensus_score = round(min(0.95, 0.7 + emission * 0.05 + mentions * 0.00005), 4)
        elif brain_action == "reduce":
            consensus_score = round(max(0.15, 0.45 - emission * 0.05 - mentions * 0.00002), 4)
        else:
            consensus_score = round(
                (quant_score * 0.4 + hype_score * 0.3 + contrarian_score * 0.3), 4
            )

        if consensus_score >= 0.75:
            action = "accumulate"
        elif consensus_score <= 0.4:
            action = "reduce"
        else:
            action = "hold"

        decisions.append(
            {
                "subnet_id": subnet_id,
                "consensus_score": consensus_score,
                "recommended_action": action,
                "expert_breakdown": {
                    "quant": {
                        "score": quant_score,
                        "metrics": {
                            "emission_stability": "high" if quant_score >= 0.7 else "low",
                            "performance_index": quant_score * 100,
                        },
                    },
                    "hype": {
                        "score": hype_score,
                        "sentiment": "bullish" if hype_score >= 0.7 else "bearish" if hype_score <= 0.4 else "neutral",
                        "metrics": {
                            "social_volume": mentions,
                            "hype_index": hype_score * 100,
                        },
                    },
                    "contrarian": {
                        "score": contrarian_score,
                        "signal": "sell" if is_overvalued else "buy",
                        "metrics": {"contrarian_index": contrarian_score * 100},
                    },
                },
                "synthesized": True,
                "brain_action": brain_action,
            }
        )
    return decisions


def _build_simivision_choices(registry, decisions, recommendations, feedback, bridge=None):
    """
    Build the top-3 SimiVision decision cards from selector output (or a
    synthesized fallback), brain recommendations, registry metadata, and the
    Adversarial Judge. Every field is derived from data already in the app so
    no placeholder picks are surfaced.
    """
    recs = recommendations.get("recommendations", {})
    alignment = feedback.get("alignment_score") if feedback else None
    alignment_status = feedback.get("status") if feedback else None

    if not decisions and registry:
        decisions = _synthesize_decisions(registry, recommendations)

    judge = AdversarialJudge()
    ranked = sorted(
        decisions,
        key=lambda d: d.get("consensus_score", 0.0) or 0.0,
        reverse=True,
    )[:3]

    choices = []
    for decision in ranked:
        subnet_id = decision.get("subnet_id")
        if subnet_id is None:
            continue
        item = registry.get(str(subnet_id), {})
        name = item.get("name") or f"Subnet {subnet_id}"
        status = item.get("status", "unknown")
        action = decision.get("recommended_action", "hold")
        confidence = decision.get("consensus_score", 0.0) or 0.0
        breakdown = decision.get("expert_breakdown", {})
        brain_rec = recs.get(str(subnet_id), {})
        brain_action = brain_rec.get("action")
        target_weight = brain_rec.get("target_weight", 0.5)

        # Apply any learned feedback boost for this subnet.
        feedback_boost = 0.0
        if bridge is not None:
            try:
                feedback_boost = bridge.get_simivision_feedback_boost(subnet_id)
            except Exception:
                feedback_boost = 0.0

        direction = 1.0 if action == "accumulate" else -1.0 if action == "reduce" else 0.0
        edge_score = round(
            (confidence + feedback_boost) * target_weight * (1.0 if direction != 0 else 0.7), 4
        )
        edge_score = max(0.0, min(1.0, edge_score))

        apy = item.get("staking_data", {}).get("apy")
        if apy:
            preferred_entry = f"Stake pool (~{apy * 100:.2f}% APY)"
        else:
            preferred_entry = "Spot accumulation" if action == "accumulate" else "Hold position"

        protocol_tag = _protocol_tag_for(name)

        risk_flags = item.get("risk_flags", []) or []
        risk_penalty = len(risk_flags) + (1 if item.get("is_overvalued") else 0)
        reward = (apy or 0.0) * 100
        risk_score = max(1, risk_penalty)
        reward_risk_ratio = round(reward / risk_score, 2)
        if reward_risk_ratio >= 15:
            reward_risk_label = "High"
        elif reward_risk_ratio >= 5:
            reward_risk_label = "Medium"
        else:
            reward_risk_label = "Low"

        quant_note = (breakdown.get("quant", {}).get("metrics") or {}).get("emission_stability", "")
        hype_sentiment = breakdown.get("hype", {}).get("sentiment", "")
        contrarian_signal = breakdown.get("contrarian", {}).get("signal", "")
        rationale_parts = []
        if decision.get("synthesized"):
            rationale_parts.append(f"Synthesized from live registry + Brain ({decision.get('brain_action', 'hold')})")
        elif action == "accumulate":
            rationale_parts.append("Consensus aligns on accumulation")
        elif action == "reduce":
            rationale_parts.append("Consensus signals reduction")
        else:
            rationale_parts.append("Consensus is neutral")
        if quant_note:
            rationale_parts.append(f"quant emission stability {quant_note}")
        if hype_sentiment:
            rationale_parts.append(f"hype sentiment {hype_sentiment}")
        if contrarian_signal:
            rationale_parts.append(f"contrarian signal {contrarian_signal}")
        why_now = "; ".join(rationale_parts) + "."

        if action == "accumulate":
            invalidation = "Consensus score falls below 0.50 or status shifts to at-risk/deprecated."
        elif action == "reduce":
            invalidation = "Consensus score rises above 0.70 with improving risk flags."
        else:
            invalidation = "Consensus moves above 0.75 or below 0.40."

        if action == "reduce":
            horizon = "Exit within 24h"
        else:
            horizon = "1–3 days"

        if brain_action:
            judge_agreement = "Agreed" if action == brain_action else "Divergent"
        else:
            judge_agreement = "No brain signal"

        # Adversarial Judge verdict for traceability.
        verdict = judge.judge_decision(
            {"recommended_action": action},
            {
                "emission": item.get("emission", 0.0),
                "social_mentions": item.get("social_mentions", 0),
                "status": status,
                "is_overvalued": item.get("is_overvalued", False),
            },
        )

        choices.append(
            {
                "subnet_id": subnet_id,
                "name": name,
                "status": status,
                "action": action,
                "confidence": confidence,
                "edge_score": edge_score,
                "feedback_boost": feedback_boost,
                "preferred_entry": preferred_entry,
                "reward_risk": {
                    "ratio": reward_risk_ratio,
                    "label": reward_risk_label,
                    "reward": round(reward, 2),
                    "risk_penalty": risk_penalty,
                },
                "why_now": why_now,
                "invalidation": invalidation,
                "horizon": horizon,
                "judge_agreement": judge_agreement,
                "brain_action": brain_action,
                "target_weight": target_weight,
                "expert_breakdown": breakdown,
                "judge_verdict": verdict,
                "metrics": {
                    "emission": item.get("emission"),
                    "social_mentions": item.get("social_mentions"),
                    "apy": apy,
                    "total_stake": item.get("staking_data", {}).get("total_stake"),
                    "is_overvalued": item.get("is_overvalued"),
                    "risk_flags": risk_flags,
                },
                "protocol_tag": protocol_tag,
            }
        )

    # Traceability: log the surfaced picks when they change.
    if bridge is not None and choices:
        pick_signature = [
            {"subnet_id": c["subnet_id"], "action": c["action"]} for c in choices
        ]
        last_picks = bridge.soul_map_state.get("last_simivision_picks", {}).get("picks")
        if pick_signature != last_picks:
            try:
                bridge.log_simivision_picks(pick_signature)
            except Exception:
                pass

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "choices": choices,
        "alignment_score": alignment,
        "alignment_status": alignment_status,
    }


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
        "freshness": freshness.overall_freshness(),
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
    bridge = MindmapBridge()
    recommendations = bridge.get_brain_recommendations()

    # Health status derived from required data files.
    health_status = "ok" if data and os.path.exists("data/soul_map.json") else "warn"

    # Top subnets for the scrolling ticker (duplicated client-side, but pre-filled here).
    ticker_items = sorted(
        enriched,
        key=lambda s: s.get("emission", 0.0) or 0.0,
        reverse=True,
    )[:12]

    freshness_state = freshness.overall_freshness()
    soul_map = load_data("data/soul_map.json")
    last_output = soul_map.get("soul_map_state", {}).get("last_selector_output", {})
    feedback = soul_map.get("feedback_logs", [None])[-1]
    simivision = _build_simivision_choices(
        data,
        last_output.get("decisions", []),
        recommendations,
        feedback,
        bridge=bridge,
    )
    watchlist = _load_watchlist()
    return render_template(
        "index.html",
        summary=summary_payload,
        registry=enriched,
        recommendations=recommendations,
        health_status=health_status,
        ticker_items=ticker_items,
        freshness=freshness_state,
        simivision=simivision,
        watchlist=watchlist,
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
    items = _enrich_registry(data)

    status_filter = request.args.get("status")
    if status_filter:
        statuses = {s.strip().lower() for s in status_filter.split(",")}
        items = [i for i in items if str(i.get("status", "")).lower() in statuses]

    protocol_filter = request.args.get("protocol")
    if protocol_filter:
        protocols = {p.strip().lower() for p in protocol_filter.split(",")}
        items = [
            i
            for i in items
            if (i.get("protocol_tag") or "").lower() in protocols
        ]

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
    item = dict(subnet_data)
    item.setdefault("id", subnet_id)
    protocol_tag = _protocol_tag_for(item.get("name", ""))
    if protocol_tag:
        item["protocol_tag"] = protocol_tag
    return jsonify({"subnet_id": subnet_id, "data": item})


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
            "freshness": freshness.overall_freshness(),
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


@app.route("/api/simivision", methods=["GET"])
def get_simivision():
    """Top-3 SimiVision choices for today with derived actionable fields."""
    soul_map = load_data("data/soul_map.json")
    last_output = soul_map.get("soul_map_state", {}).get("last_selector_output", {})
    bridge = MindmapBridge()
    recommendations = bridge.get_brain_recommendations()
    feedback = soul_map.get("feedback_logs", [None])[-1]
    registry = load_data("config/registry.json")
    simivision = _build_simivision_choices(
        registry,
        last_output.get("decisions", []),
        recommendations,
        feedback,
        bridge=bridge,
    )
    return jsonify(
        {
            "status": "success",
            "freshness": _freshness_meta("soul_map"),
            "data": simivision,
        }
    )


@app.route("/api/mindmap/feedback", methods=["POST"])
def post_feedback():
    feedback = request.get_json(silent=True)
    return jsonify({"status": "received", "feedback": feedback})


@app.route("/api/watchlist", methods=["GET"])
def get_watchlist():
    """Return the first-class protocol watchlist."""
    data = _load_watchlist()
    return jsonify(
        {
            "status": "success",
            "freshness": _freshness_meta("watchlist"),
            "data": data,
        }
    )


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
