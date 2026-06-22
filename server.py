import json
import os
import time
from datetime import datetime

from flask import Flask, jsonify, render_template, request

from internal.council.mindmap_bridge import MindmapBridge
from internal.council.judge.adversarial import AdversarialJudge
from internal import freshness
from internal import scheduler as adversarial_scheduler
from internal.signals.signal_tracker import SignalTracker
from internal.indicators import indicator_scheduler
from internal.indicators.indicator_engine import IndicatorEngine
from internal.simivision.engine import (
    SimiVisionEngine,
    _load_selector_decisions,
    _synthesize_decision,
)

app = Flask(__name__)
bridge = MindmapBridge()

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

def _app_version():
    """Return the dashboard version declared in the protocols config."""
    return load_data(_PROTOCOLS_PATH).get("meta", {}).get("version", "unknown")

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
        # Run request-triggered scheduler checks on each request
        _check_schedulers()
        return
    _background_sync_started = True
    if app.config["ENABLE_BACKGROUND_SYNC"] and not app.config.get("TESTING"):
        freshness.merge_remote_registry()
        freshness.start_background_sync(immediate=True)
        indicator_scheduler.start_indicator_scheduler(immediate=True)
        adversarial_scheduler.start_adversarial_scheduler(immediate=True)

def _check_schedulers():
    """Check and run schedulers on each request (request-triggered model)."""
    try:
        # Check adversarial scheduler (1 hour threshold)
        adv_scheduler = adversarial_scheduler.get_adversarial_scheduler()
        if adv_scheduler:
            adv_scheduler.check_and_run()
    except Exception:
        pass
    
    try:
        # Check indicator scheduler (5 minute threshold)
        ind_scheduler = indicator_scheduler.get_indicator_scheduler()
        if ind_scheduler:
            ind_scheduler.check_and_run()
    except Exception:
        pass
    
    try:
        # Check freshness (registry refresh)
        freshness.check_and_refresh_registry()
    except Exception:
        pass


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
    elif source == "signal_timeline":
        info = freshness.signal_timeline_freshness()
    elif source == "price_cache":
        info = freshness.price_data_freshness()
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


def _nested_get(obj, path, default=None):
    """Safely fetch a dotted path from a dict (e.g. 'staking_data.apy')."""
    value = obj
    for part in path.split("."):
        if not isinstance(value, dict):
            return default
        value = value.get(part, default)
    return value


def _synthetic_breakdown(item):
    """Build a minimal traceable expert breakdown from registry metadata."""
    emission = item.get("emission", 0.0) or 0.0
    mentions = item.get("social_mentions", 0) or 0
    is_overvalued = item.get("is_overvalued", False)

    quant_score = 0.85 if emission > 1.0 else 0.4 if emission < 0.2 else 0.75
    hype_score = 0.9 if mentions > 1000 else 0.3 if mentions < 100 else 0.65
    contrarian_score = 0.2 if is_overvalued else 0.8

    return {
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
    }


def _simivision_rationale(action, breakdown, source_note=None):
    """Build a human-readable rationale string for a SimiVision card."""
    quant_note = (breakdown.get("quant", {}).get("metrics") or {}).get("emission_stability", "")
    hype_sentiment = breakdown.get("hype", {}).get("sentiment", "")
    contrarian_signal = breakdown.get("contrarian", {}).get("signal", "")
    rationale_parts = []
    if source_note:
        rationale_parts.append(source_note)
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
    return "; ".join(rationale_parts) + "."


def _build_choice(registry, recs, decision, judge, feedback_boost=0.0):
    """Build a single SimiVision choice from a decision-like object."""
    subnet_id = decision.get("subnet_id")
    item = registry.get(str(subnet_id), {}) if registry else {}
    name = item.get("name") or f"Subnet {subnet_id}"
    status = item.get("status", "unknown")
    action = decision.get("recommended_action", "hold")
    confidence = decision.get("consensus_score", 0.0) or 0.0
    breakdown = decision.get("expert_breakdown", {})
    brain_rec = recs.get(str(subnet_id), {}) if recs else {}
    brain_action = brain_rec.get("action")
    target_weight = brain_rec.get("target_weight", 0.5)

    direction = 1.0 if action == "accumulate" else -1.0 if action == "reduce" else 0.0
    edge_score = round(
        (confidence + feedback_boost)
        * target_weight
        * (1.0 if direction != 0 else 0.7),
        4,
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

    source_note = None
    if decision.get("from_brain"):
        source_note = f"Brain recommendation ({brain_action or 'hold'})"
    elif decision.get("from_registry"):
        source_note = f"Registry highlight: {decision.get('registry_highlight', 'metric')}"

    why_now = _simivision_rationale(action, breakdown, source_note)

    if action == "accumulate":
        invalidation = "Consensus score falls below 0.50 or status shifts to at-risk/deprecated."
    elif action == "reduce":
        invalidation = "Consensus score rises above 0.70 with improving risk flags."
    else:
        invalidation = "Consensus moves above 0.75 or below 0.40."

    horizon = "Exit within 24h" if action == "reduce" else "1–3 days"

    if brain_action:
        judge_agreement = "Agreed" if action == brain_action else "Divergent"
    else:
        judge_agreement = "No brain signal"

    verdict = judge.judge_decision(
        {"recommended_action": action},
        {
            "emission": item.get("emission", 0.0),
            "social_mentions": item.get("social_mentions", 0),
            "status": status,
            "is_overvalued": item.get("is_overvalued", False),
        },
    )

    return {
        "subnet_id": subnet_id,
        "name": name,
        "status": status,
        "action": action,
        "confidence": confidence,
        "edge_score": edge_score,
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
        "feedback_boost": feedback_boost,
    }


@app.route("/")
def index():
    registry = load_data("config/registry.json")
    watchlist = _load_watchlist()
    if not registry:
        return render_template("loading.html")
    enriched = _enrich_registry(registry)
    # Use SimiVision engine for the homepage
    engine = SimiVisionEngine(registry_path="config/registry.json")
    simi_data = engine.safe_snapshot()
    return render_template(
        "index.html",
        data=enriched,
        watchlist=watchlist,
        version=_app_version(),
        freshness=_freshness_meta("registry"),
        simivision_data=simi_data,
    )


@app.route("/health")
def health():
    return "OK"


@app.route("/api/registry")
def registry():
    return jsonify(load_data("config/registry.json"))


@app.route("/api/watchlist")
def watchlist():
    return jsonify(_load_watchlist())


@app.route("/api/freshness")
def freshness_api():
    return jsonify(_freshness_meta("registry"))


@app.route("/api/simivision")
def simivision():
    """Return the SimiVision snapshot for the homepage."""
    engine = SimiVisionEngine(registry_path="config/registry.json")
    return jsonify(engine.safe_snapshot())


@app.route("/api/simivision/<int:netuid>/trace")
def simivision_trace(netuid):
    """Return deep trace for a specific subnet."""
    try:
        engine = SimiVisionEngine(registry_path="config/registry.json")
        registry = load_data("config/registry.json")
        decisions = _load_selector_decisions()
        trace = _synthesize_decision(engine, registry, decisions, netuid)
        if trace is None:
            return jsonify({"error": "subnet not found"}), 404
        return jsonify(trace)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/mindmap/feedback", methods=["POST"])
def mindmap_feedback():
    """Record user feedback on a SimiVision pick."""
    data = request.get_json() or {}
    subnet_id = data.get("subnet_id")
    outcome = data.get("outcome")
    note = data.get("note", "")
    if subnet_id is None or outcome is None:
        return jsonify({"error": "subnet_id and outcome required"}), 400
    try:
        bridge.log_simivision_picks([{
            "subnet_id": subnet_id,
            "outcome": outcome,
            "note": note,
        }])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/scheduler/state")
def scheduler_state():
    """Return the state of all schedulers."""
    return jsonify({
        "adversarial": adversarial_scheduler.get_adversarial_scheduler_state(),
        "indicators": indicator_scheduler.get_indicator_scheduler_state(),
        "freshness": freshness._sync_state,
    })


@app.route("/api/scheduler/adversarial/check", methods=["POST"])
def check_adversarial():
    """Trigger a check on the adversarial scheduler."""
    scheduler = adversarial_scheduler.get_adversarial_scheduler()
    if scheduler:
        result = scheduler.check_and_run()
        return jsonify(result)
    return jsonify({"error": "scheduler not running"}), 400


@app.route("/api/scheduler/indicators/check", methods=["POST"])
def check_indicators():
    """Trigger a check on the indicator scheduler."""
    scheduler = indicator_scheduler.get_indicator_scheduler()
    if scheduler:
        result = scheduler.check_and_run()
        return jsonify(result)
    return jsonify({"error": "scheduler not running"}), 400


@app.route("/api/freshness/refresh", methods=["POST"])
def refresh_freshness():
    """Trigger a registry refresh."""
    result = freshness.check_and_refresh_registry(immediate=True)
    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))