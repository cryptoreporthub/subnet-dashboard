import json
import os
import threading
from datetime import datetime
from typing import Any, Dict

from flask import Flask, jsonify, render_template, request

# Ensure the data directory exists at module load time (critical for Fly.io).
os.makedirs('data', exist_ok=True)

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

# Protocol watchlist configuration: first-class scan targets surfaced in the UI.
_PROTOCOLS_PATH = os.environ.get("PROTOCOLS_PATH", "config/protocols.json")
_protocols_config = {}

# Freshness configuration
app.config["ENABLE_BACKGROUND_SYNC"] = (
    os.environ.get("ENABLE_BACKGROUND_SYNC", "true").lower() != "false"
)

def load_data(filename):
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return json.load(f)
    return {}

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

# Lazily start the background sync once on the first request so it works
# under both `python server.py` and gunicorn without import-time side effects.
_background_sync_started = False

@app.before_request
def _ensure_background_sync():
    """Start background sync on first request and trigger scheduler refresh."""
    global _background_sync_started
    if _background_sync_started:
        # On subsequent requests, check if adversarial scheduler needs refresh
        # This handles Fly.io auto-stop cold starts
        if app.config.get("ENABLE_BACKGROUND_SYNC") and not app.config.get("TESTING"):
            # Run scheduler refresh in background to avoid blocking response
            try:
                scheduler = adversarial_scheduler.get_adversarial_scheduler()
                if scheduler:
                    threading.Thread(target=scheduler.check_and_run, daemon=True).start()
            except Exception:
                pass
        return
    _background_sync_started = True
    if app.config["ENABLE_BACKGROUND_SYNC"] and not app.config.get("TESTING"):
        # Run initial sync in a background thread to avoid blocking the first
        # request — merge_remote_registry performs a synchronous HTTP fetch with
        # a 30-second timeout that would exceed gunicorn's default 30-second
        # worker timeout, causing an HTTP 500 on cold start.
        def _initial_sync():
            freshness.merge_remote_registry()
            freshness.start_background_sync(immediate=True)
            indicator_scheduler.start_indicator_scheduler(immediate=True)
            adversarial_scheduler.start_adversarial_scheduler(immediate=True)
        threading.Thread(target=_initial_sync, daemon=True).start()

@app.route('/health')
def health():
    return "OK"

@app.route('/api/scheduler/state')
def scheduler_state():
    """Return the current state of the adversarial scheduler."""
    return jsonify(adversarial_scheduler.get_adversarial_scheduler_state())

def _build_summary(registry: Dict[str, Any]) -> Dict[str, Any]:
    """Build a network-health summary dict from the registry."""
    total = len(registry)
    active = sum(1 for v in registry.values() if v.get("status") == "active")
    flagged = sum(1 for v in registry.values() if v.get("risk_flags"))
    at_risk = sum(1 for v in registry.values() if "at_risk" in v.get("risk_flags", []))
    deprecated = sum(1 for v in registry.values() if v.get("status") == "deprecated")
    overvalued = sum(1 for v in registry.values() if v.get("is_overvalued"))
    total_emission = sum(v.get("emission", 0.0) for v in registry.values())
    total_stake = sum(
        v.get("staking_data", {}).get("total_stake", 0.0)
        for v in registry.values()
    )
    total_apy = sum(v.get("apy", 0.0) for v in registry.values())
    avg_apy = total_apy / total if total else 0.0
    network_health = active / total if total else 0.0

    statuses = [v.get("status", "unknown") for v in registry.values()]
    status_counts: Dict[str, int] = {}
    for s in statuses:
        status_counts[s] = status_counts.get(s, 0) + 1
    status_distribution = {
        s: round(c / total, 4) if total else 0.0
        for s, c in status_counts.items()
    }

    # Spotlight arrays – template expects array-of-objects
    def _to_spotlight(val_field, name_field="name"):
        """Return a list with one item: the top active subnet by val_field."""
        items = [(k, v) for k, v in registry.items() if v.get("status") == "active"]
        if not items:
            return []
        best = max(items, key=lambda kv: kv[1].get(val_field, 0.0))
        obj: Dict[str, Any] = {
            "id": int(best[0]),
            "name": best[1].get(name_field, f"Subnet {best[0]}"),
        }
        obj[val_field] = best[1].get(val_field, 0.0)
        return [obj]

    highlights = {
        "top_emitter": _to_spotlight("emission"),
        "top_apy": _to_spotlight("apy"),
        "most_mentioned": _to_spotlight("social_mentions"),
        "top_consensus": [],
        "riskiest": [],
    }
    # consensus spotlight
    active_items = [(k, v) for k, v in registry.items() if v.get("status") == "active"]
    if active_items:
        best = max(active_items, key=lambda kv: kv[1].get("consensus_score", 0.0))
        highlights["top_consensus"] = [{
            "id": int(best[0]),
            "name": best[1].get("name", f"Subnet {best[0]}"),
            "consensus_score": best[1].get("consensus_score", 0.0),
            "status": best[1].get("status", "active"),
            "recommended_action": best[1].get("recommended_action", "hold"),
            "protocol_tag": None,
        }]
        worst = min(active_items, key=lambda kv: kv[1].get("consensus_score", 1.0))
        highlights["riskiest"] = [{
            "id": int(worst[0]),
            "name": worst[1].get("name", f"Subnet {worst[0]}"),
            "consensus_score": worst[1].get("consensus_score", 0.0),
            "status": worst[1].get("status", "active"),
            "recommended_action": worst[1].get("recommended_action", "hold"),
            "protocol_tag": None,
        }]

    return {
        "last_updated": datetime.utcnow().isoformat(),
        "network_health": round(network_health, 4),
        "active_count": active,
        "total_subnets": total,
        "flagged_count": flagged,
        "at_risk_count": at_risk,
        "deprecated_count": deprecated,
        "overvalued_count": overvalued,
        "total_emission": round(total_emission, 4),
        "total_stake": round(total_stake, 2),
        "avg_apy": round(avg_apy, 4),
        "status_counts": status_counts,
        "status_distribution": status_distribution,
        "highlights": highlights,
    }


def _pick_hero(simivision_signals: list, registry: Dict[str, Any]) -> Dict[str, Any]:
    """Pick the top conviction asset as the dashboard hero."""
    if not simivision_signals:
        for k, v in registry.items():
            try:
                return {"netuid": int(k), "name": v.get("name", f"Subnet {k}"), "conviction": 50.0, "status": "active", "rank": 1, "rationale": "Registry default", "delta": "", "delta_value": 0, "freshness_human": "Unknown"}
            except (ValueError, TypeError):
                continue
    top = simivision_signals[0]
    delta = top.get("delta", "")
    delta_value = top.get("delta_value", 0)
    return {
        "netuid": top.get("netuid", 1),
        "name": top.get("name", "Unknown"),
        "conviction": top.get("conviction", 50.0),
        "status": top.get("status", "active"),
        "rank": top.get("rank", 1),
        "rationale": top.get("rationale", ""),
        "delta": "+" if delta_value and delta_value > 0 else ("-" if delta_value and delta_value < 0 else ""),
        "delta_value": delta_value,
        "freshness_human": top.get("freshness_human", "Unknown"),
    }


# ── Spotlight helpers ──────────────────────────────────────────────────────────
def _top_emitter(registry):
    items = [(k, v) for k, v in registry.items() if v.get("status") == "active"]
    if not items:
        return {"name": "—", "emission": 0.0}
    best = max(items, key=lambda kv: kv[1].get("emission", 0.0))
    return {"name": best[1].get("name", f"Subnet {best[0]}"), "emission": best[1].get("emission", 0.0)}


def _top_apy(registry):
    items = [(k, v) for k, v in registry.items() if v.get("status") == "active"]
    if not items:
        return {"name": "—", "apy": 0.0}
    best = max(items, key=lambda kv: kv[1].get("apy", 0.0))
    return {"name": best[1].get("name", f"Subnet {best[0]}"), "apy": best[1].get("apy", 0.0)}


def _most_mentioned(registry):
    items = [(k, v) for k, v in registry.items() if v.get("status") == "active"]
    if not items:
        return {"name": "—", "social_mentions": 0}
    best = max(items, key=lambda kv: kv[1].get("social_mentions", 0))
    return {"name": best[1].get("name", f"Subnet {best[0]}"), "social_mentions": best[1].get("social_mentions", 0)}


def _riskiest(registry):
    items = [(k, v) for k, v in registry.items() if v.get("status") == "active"]
    if not items:
        return {"name": "—", "consensus_score": 0.0}
    worst = min(items, key=lambda kv: kv[1].get("consensus_score", 1.0))
    return {"name": worst[1].get("name", f"Subnet {worst[0]}"), "consensus_score": worst[1].get("consensus_score", 0.0)}


@app.route('/')
def index():
    """Render the main dashboard homepage with full template context."""
    registry = load_data("config/registry.json")

    summary_inner = _build_summary(registry)
    ctx: Dict[str, Any] = {
        "app_version": _app_version(),
        "health_status": "ok",
        "freshness": {
            "overall": {"any_stale": False, "checked_at": datetime.utcnow().isoformat()},
            "age_label": "Recently",
            "signal_timeline": {"age_label": "Recently"},
        },
        "summary": {
            "summary": summary_inner,
            "highlights": summary_inner["highlights"],
        },
        "top_emitter": _top_emitter(registry),
        "top_apy": _top_apy(registry),
        "most_mentioned": _most_mentioned(registry),
        "riskiest": _riskiest(registry),
        "watchlist": {"last_updated": "unknown", "protocols": []},
        "simivision": {},
        "signal_timeline": {"updated_at": "unknown", "assets": {}},
        "hero": {"netuid": 1, "name": "Apex", "conviction": 50, "status": "active", "rank": 1, "rationale": "", "delta": "", "delta_value": 0, "freshness_human": "Unknown"},
    }

    # ── Freshness snapshot ─────────────────────────────────────────────────────
    try:
        ctx["freshness"] = freshness.overall_freshness()
    except Exception:
        pass

    # ── SimiVision snapshot ────────────────────────────────────────────────────
    simivision_signals: list = []
    try:
        engine = SimiVisionEngine()
        snap = engine.safe_snapshot(n=5)
        ctx["simivision"] = snap
        simivision_signals = snap.get("top", [])
    except Exception:
        ctx["simivision"] = {
            "top": [],
            "choices": [],
            "meta": {
                "system_status": "Operative",
                "source": "offline",
                "fallback_used": True,
                "error": "SimiVision unavailable",
                "freshness_human": "Unknown",
                "provenance_log": [],
            },
        }

    # ── Hero card ──────────────────────────────────────────────────────────────
    ctx["hero"] = _pick_hero(simivision_signals, registry)

    # ── Watchlist ──────────────────────────────────────────────────────────────
    try:
        wl = load_data("config/watchlist.json")
        protocols_data = wl.get("protocols", {})
        ctx["watchlist"] = {
            "last_updated": wl.get("last_updated", "unknown"),
            "protocols": [
                {
                    "symbol": p.get("symbol"),
                    "name": p.get("name"),
                    "category": p.get("category"),
                    "status": p.get("status"),
                    "price": p.get("price"),
                    "change_24h": p.get("change_24h"),
                    "mentions": p.get("mentions"),
                    "tags": p.get("tags", []),
                    "url": p.get("url"),
                    "description": p.get("description"),
                }
                for p in protocols_data.values()
            ],
        }
    except Exception:
        pass

    # ── Signal timeline ────────────────────────────────────────────────────────
    try:
        st = load_data("data/signal_timeline.json")
        assets = st.get("assets", {})
        structured: Dict[str, Any] = {}
        for symbol, record in assets.items():
            metrics = {
                "signal_count": record.get("signal_count", 0),
                "distinct_sources": len(record.get("sources", [])),
                "time_to_pump_seconds": None,
                "pump_duration_seconds": None,
                "time_to_resurgence_seconds": None,
            }
            pump_start = record.get("pump_started_at")
            first_signal = record.get("first_signal_at")
            if pump_start and first_signal:
                try:
                    ps = datetime.fromisoformat(pump_start)
                    fs = datetime.fromisoformat(first_signal)
                    metrics["time_to_pump_seconds"] = (ps - fs).total_seconds()
                except Exception:
                    pass
            pump_end = record.get("pump_ended_at")
            if pump_end and pump_start:
                try:
                    pe = datetime.fromisoformat(pump_end)
                    ps = datetime.fromisoformat(pump_start)
                    metrics["pump_duration_seconds"] = (pe - ps).total_seconds()
                except Exception:
                    pass
            resurgence = record.get("resurgence_at")
            if resurgence and pump_end:
                try:
                    rs = datetime.fromisoformat(resurgence)
                    pe = datetime.fromisoformat(pump_end)
                    metrics["time_to_resurgence_seconds"] = (rs - pe).total_seconds()
                except Exception:
                    pass
            structured[symbol] = {**record, "metrics": metrics}
        ctx["signal_timeline"] = {
            "updated_at": st.get("updated_at", "unknown"),
            "assets": structured,
        }
    except Exception:
        pass

    return render_template("index.html", **ctx)

@app.route('/registry')
def registry():
    data = load_data('config/registry.json')
    return jsonify(data)

@app.route('/registry/<int:subnet_id>')
def subnet_detail(subnet_id):
    data = load_data('config/registry.json')
    item = data.get(str(subnet_id), {})
    return jsonify(item)

@app.route('/api/mindmap/nodes')
def mindmap_nodes():
    """Return active and pruned mindmap nodes with decay values."""
    from internal.conviction_decay import get_decay_state
    return jsonify(get_decay_state())

@app.route('/api/mindmap/hypotheses')
def mindmap_hypotheses():
    """Return pending hypotheses."""
    from internal.conviction_decay import get_hypotheses
    include_resolved = request.args.get('include_resolved', 'false').lower() == 'true'
    return jsonify(get_hypotheses(include_resolved=include_resolved))

@app.route('/api/mindmap/hypotheses', methods=['POST'])
def create_hypothesis():
    """Record a new testable hypothesis."""
    from internal.conviction_decay import create_hypothesis
    body = request.get_json() or {}
    result = create_hypothesis(
        prediction=body.get('prediction'),
        horizon=body.get('horizon'),
        sources=body.get('sources', []),
        subnet_id=body.get('subnet_id'),
    )
    return jsonify(result)

@app.route('/api/mindmap/hypotheses/<int:hypothesis_id>/resolve', methods=['POST'])
def resolve_hypothesis(hypothesis_id):
    """Resolve a hypothesis against current price data."""
    from internal.conviction_decay import resolve_hypothesis
    result = resolve_hypothesis(hypothesis_id)
    return jsonify(result)

@app.route('/api/price-oracle/')
def price_oracle_single():
    """Return price for a single token."""
    from internal.price_oracle import get_token_price
    token = request.args.get('token', 'TAO')
    price = get_token_price(token)
    return jsonify({"token": token, "price": price})

@app.route('/api/price-oracle')
def price_oracle_all():
    """Return all tracked token prices."""
    from internal.price_oracle import get_all_prices
    prices = get_all_prices()
    return jsonify(prices)

@app.route('/simivision')
def simivision():
    """Render the SimiVision dashboard."""
    registry = load_data('config/registry.json')
    soul_map = load_data('data/soul_map.json')
    last_output = soul_map.get('soul_map_state', {}).get('last_selector_output', {})
    decisions = last_output.get('decisions', [])
    consensus = {d['subnet_id']: d for d in decisions if 'subnet_id' in d}
    
    items = []
    for key, value in registry.items():
        item = dict(value)
        subnet_id = item.get('id', int(key))
        item.setdefault('id', subnet_id)
        decision = consensus.get(subnet_id)
        if decision:
            item['consensus'] = {
                'score': decision.get('consensus_score'),
                'recommended_action': decision.get('recommended_action'),
                'expert_breakdown': decision.get('expert_breakdown'),
            }
        items.append(item)
    
    return render_template('simivision.html', items=items)

@app.route('/api/simivision')
def api_simivision():
    """Return SimiVision signals with conviction/rationale/delta fields."""
    try:
        engine = SimiVisionEngine()
        signals = engine.get_signals()
        return jsonify({"signals": signals})
    except Exception as e:
        return jsonify({"signals": [], "error": str(e)}), 500
@app.route('/api/signal/<int:subnet_id>/timeline')
def signal_timeline(subnet_id):
    """Return signal timeline for a subnet."""
    from internal.signals.signal_tracker import get_signal_timeline
    timeline = get_signal_timeline(subnet_id)
    return jsonify(timeline)

@app.route('/api/indicators')
def indicators():
    """Return current indicator values for all subnets."""
    from internal.indicators.indicator_engine import IndicatorEngine
    indicators = IndicatorEngine().get_indicator_state()
    return jsonify(indicators)

@app.route('/api/scheduler/run', methods=['POST'])
def run_scheduler():
    """Trigger a manual scheduler run."""
    scheduler = adversarial_scheduler.get_adversarial_scheduler()
    if scheduler:
        result = scheduler.run_once()
        return jsonify(result)
    return jsonify({"error": "scheduler not running"}), 500

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "not found"}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "internal server error"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)