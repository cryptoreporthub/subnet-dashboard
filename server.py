import json
import os
import threading
from datetime import datetime

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
        freshness.merge_remote_registry()
        freshness.start_background_sync(immediate=True)
        indicator_scheduler.start_indicator_scheduler(immediate=True)
        adversarial_scheduler.start_adversarial_scheduler(immediate=True)

@app.route('/health')
def health():
    return "OK"

@app.route('/api/scheduler/state')
def scheduler_state():
    """Return the current state of the adversarial scheduler."""
    return jsonify(adversarial_scheduler.get_adversarial_scheduler_state())

@app.route('/')
def index():
    return render_template('index.html', **{})

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
    """Return SimiVision data for the current cycle."""
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
            }
        items.append(item)
    
    return jsonify(items)

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