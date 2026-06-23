import json
import os
import threading
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
    """Start background sync on first request and trigger scheduler refresh."""
    global _background_sync_started
    if _background_sync_started:
        # On subsequent requests, check if adversarial scheduler needs refresh
        # This handles Fly.io auto-stop cold starts
        if app.config.get("ENABLE_BACKGROUND_SYNC") and not app.config.get("TESTING"):
            # Run scheduler refresh in background to avoid blocking response
            try:
                adversarial_scheduler.get_adversarial_scheduler_state()
                threading.Thread(
                    target=lambda: adversarial_scheduler.get_adversarial_scheduler().check_and_run() if adversarial_scheduler.get_adversarial_scheduler() else None,
                    daemon=True
                ).start()
            except Exception:
                pass
        return
    _background_sync_started = True
    if app.config["ENABLE_BACKGROUND_SYNC"] and not app.config.get("TESTING"):
        freshness.merge_remote_registry()
        freshness.start_background_sync(immediate=True)
        indicator_scheduler.start_indicator_scheduler(immediate=True)
        adversarial_scheduler.start_adversarial_scheduler(immediate=True)

@app.route('/api/scheduler/state')
def scheduler_state():
    """Return the current state of the adversarial scheduler."""
    return jsonify(adversarial_scheduler.get_adversarial_scheduler_state())