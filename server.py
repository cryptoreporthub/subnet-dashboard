"""
Subnet Dashboard — Flask application serving the Bittensor intelligence UI.

Integrates the Message Intelligence Pipeline for Telegram monitoring,
NLP analysis, jury evaluation, price tracking, and self-learning.
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, jsonify, request, render_template

from internal.council.judge.adversarial import AdversarialJudge
from internal.council.learner import LearningLoop
from internal.council.mindmap_bridge import MindmapBridge
from internal.freshness import start_background_sync, registry_freshness, soul_map_freshness
from internal.simivision.engine import SimiVisionEngine

from message_intel import Database, NLPAnalyzer, JuryBridge, PriceTracker, SelfLearning

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(
    __name__,
    template_folder="templates",
    static_url_path="/static",
    static_folder="static",
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global instances
# ---------------------------------------------------------------------------

db = Database()
nlp = NLPAnalyzer()
judge = AdversarialJudge()
mindmap = MindmapBridge()
jury_bridge = JuryBridge(judge=judge, mindmap=mindmap)
price_tracker = PriceTracker(db=db)
self_learning = SelfLearning(db=db, judge=judge)
simivision = SimiVisionEngine()

# ---------------------------------------------------------------------------
# Telegram listener (lazy start)
# ---------------------------------------------------------------------------

_telegram_listener = None
_telegram_started = False


def _start_telegram_listener():
    """Start the Telegram listener in a background thread (called once)."""
    global _telegram_listener, _telegram_started
    if _telegram_started:
        return
    _telegram_started = True

    try:
        from message_intel.telegram_listener import TelegramListener

        api_id = os.environ.get("TELEGRAM_API_ID")
        api_hash = os.environ.get("TELEGRAM_API_HASH")

        if not api_id or not api_hash:
            logger.info(
                "TELEGRAM_API_ID/HASH not set — skipping Telegram listener"
            )
            return

        _telegram_listener = TelegramListener(
            api_id=api_id,
            api_hash=api_hash,
            phone=os.environ.get("TELEGRAM_PHONE"),
            group=os.environ.get("TELEGRAM_GROUP", "OfficialSubnetSummer"),
        )
        _telegram_listener.start()
        logger.info("Telegram listener background thread started")
    except ImportError as e:
        logger.warning("Could not start Telegram listener: %s", e)
    except Exception as e:
        logger.error("Failed to start Telegram listener: %s", e)


def _start_background_tasks():
    """Start background tasks after the first request or on startup."""
    _start_telegram_listener()
    price_tracker.start_background_checks(interval=300)
    self_learning.start_background_learning(interval=600)

    # Start freshness sync
    try:
        start_background_sync()
    except Exception as e:
        logger.warning("Freshness sync not available: %s", e)


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------

def json_response(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            result = f(*args, **kwargs)
            if isinstance(result, tuple):
                data, status = result
                return jsonify(data), status
            if isinstance(result, dict) and "error" in result:
                return jsonify(result), result.get("_status", 400)
            # Wrap in standard envelope
            return jsonify({"status": "success", "data": result})
        except Exception as e:
            logger.exception("Error in %s", f.__name__)
            return jsonify({"status": "error", "error": str(e)}), 500
    return wrapper


# ---------------------------------------------------------------------------
# Routes — Core
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Serve the main dashboard."""
    try:
        simivision_data = simivision.safe_snapshot(n=5)
    except Exception:
        simivision_data = {
            "top": [],
            "meta": {"system_status": "Error", "source": "offline"},
        }

    return render_template(
        "index.html",
        ticker_items=[],
        simivision=simivision_data,
        summary={"highlights": {}},
    )


@app.route("/health")
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})


# ---------------------------------------------------------------------------
# Routes — Message Intelligence
# ---------------------------------------------------------------------------

@app.route("/api/messages/ingest", methods=["POST"])
def ingest_message():
    """
    Receive a normalized message from the Telegram listener (or any source).

    Pipeline: save message → run NLP → run jury → record price → store.
    """
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "No data provided"}), 400

        content = data.get("content", "")
        if not content:
            return jsonify({"error": "Empty message content"}), 400

        # 1. Save the raw message
        message_id = db.save_message(data)
        logger.info("Ingested message %d from %s", message_id, data.get("source", "unknown"))

        # 2. Run NLP analysis
        analysis = nlp.analyze(content)
        db.save_analysis(message_id, analysis)

        # 3. Run jury evaluation
        verdict = jury_bridge.evaluate(message_id, content, analysis)
        db.save_verdict(message_id, verdict)

        # 4. Record price snapshot for high-conviction messages
        conviction = verdict.get("conviction", 0)
        if conviction >= 60:
            price_tracker.snapshot(message_id)

        return jsonify({
            "status": "success",
            "data": {
                "message_id": message_id,
                "analysis": analysis,
                "verdict": verdict,
            },
        }), 201
    except Exception as e:
        logger.exception("Ingest error")
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/messages", methods=["GET"])
@json_response
def list_messages():
    """List recent analyzed messages with verdicts."""
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)
    messages = db.list_messages(limit=limit, offset=offset)
    return {
        "messages": messages,
        "total": len(messages),
    }


@app.route("/api/messages/<int:message_id>", methods=["GET"])
@json_response
def get_message(message_id: int):
    """Get a specific message with full analysis."""
    msg = db.get_message(message_id)
    if not msg:
        return {"error": "Message not found"}, 404
    return msg


@app.route("/api/chatter", methods=["GET"])
@json_response
def chatter_brief():
    """
    Community intelligence brief summary.

    Returns aggregate stats and recent high-conviction signals.
    """
    recent = db.list_messages(limit=20)
    high_conviction = db.list_high_conviction_messages(min_conviction=0.6)

    # Compute aggregate stats
    sentiments = {"bullish": 0, "bearish": 0, "neutral": 0}
    total_hype = 0.0
    total_substance = 0.0
    msg_count = len(recent)

    for m in recent:
        a = m.get("analysis") or {}
        s = a.get("sentiment", "neutral")
        sentiments[s] = sentiments.get(s, 0) + 1
        total_hype += a.get("hype_score", 0)
        total_substance += a.get("substance_score", 0)

    avg_hype = round(total_hype / msg_count, 4) if msg_count else 0
    avg_substance = round(total_substance / msg_count, 4) if msg_count else 0

    # Determine the dominant sentiment
    dominant = max(sentiments, key=sentiments.get)
    total_sentiment = sum(sentiments.values())
    sentiment_distribution = {
        k: round(v / total_sentiment * 100, 1) if total_sentiment else 0
        for k, v in sentiments.items()
    }

    return {
        "total_messages_analyzed": msg_count,
        "dominant_sentiment": dominant,
        "sentiment_distribution": sentiment_distribution,
        "avg_hype_score": avg_hype,
        "avg_substance_score": avg_substance,
        "high_conviction_signals": len(high_conviction),
        "recent_signals": [
            {
                "id": m["id"],
                "content_preview": m.get("content", "")[:120],
                "sentiment": m.get("analysis", {}).get("sentiment") if m.get("analysis") else None,
                "verdict": m.get("verdict", {}).get("verdict") if m.get("verdict") else None,
                "conviction": m.get("verdict", {}).get("conviction") if m.get("verdict") else None,
            }
            for m in recent[:10]
        ],
    }


@app.route("/api/patterns", methods=["GET"])
@json_response
def list_patterns():
    """Return discovered pattern correlations."""
    patterns = db.list_patterns(limit=20)
    return {"patterns": patterns}


# ---------------------------------------------------------------------------
# Routes — Existing Council / SimiVision
# ---------------------------------------------------------------------------

@app.route("/api/simivision")
@json_response
def get_simivision():
    """Return SimiVision top picks."""
    try:
        signals = simivision.get_signals()
        top = signals[:5] if signals else []
        return {
            "top": top,
            "meta": {
                "system_status": "Operative",
                "source": "engine",
            },
        }
    except Exception as e:
        logger.exception("SimiVision error")
        return {
            "top": [],
            "meta": {"system_status": "Error", "source": "offline", "error": str(e)},
        }


@app.route("/api/daily-rotation")
@json_response
def get_daily_rotation():
    """Run and return the daily council rotation."""
    from internal.council.orchestrator import Orchestrator
    orch = Orchestrator()
    result = orch.run_daily_rotation()
    return result


@app.route("/api/learning-trail")
@json_response
def get_learning_trail():
    """Return the adversarial judge's learning trail."""
    trail = judge.get_learning_trail(limit=50)
    return {"trail": trail}


@app.route("/api/learning/run", methods=["POST"])
@json_response
def run_learning():
    """Manually trigger the learning loop."""
    learner = LearningLoop()
    result = learner.run()
    return result


@app.route("/api/mindmap/feedback", methods=["POST"])
@json_response
def post_feedback():
    """Record user feedback for a SimiVision pick."""
    data = request.get_json(force=True)
    subnet_id = data.get("subnet_id")
    outcome = data.get("outcome", 0)
    note = data.get("note", "")
    if subnet_id is None:
        return {"error": "subnet_id is required"}, 400
    entry = mindmap.log_simivision_feedback(subnet_id, outcome, note)
    return entry


# ---------------------------------------------------------------------------
# Routes — Legacy endpoints for backward compatibility with existing tests
# ---------------------------------------------------------------------------

@app.route("/api/freshness")
def get_freshness():
    """Return data freshness info (legacy endpoint)."""
    from internal.freshness import (
        overall_freshness,
        registry_freshness as _registry_freshness,
        soul_map_freshness,
        recommendations_freshness,
        watchlist_freshness,
    )

    try:
        return jsonify({
            "status": "success",
            "data": {
                "freshness": {
                    "registry": _registry_freshness(),
                    "soul_map": soul_map_freshness(),
                    "recommendations": recommendations_freshness(),
                    "watchlist": watchlist_freshness(),
                    "overall": overall_freshness(),
                },
            },
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/sync", methods=["POST"])
def post_sync():
    """Trigger a data sync (legacy endpoint)."""
    from internal.freshness import refresh_all, refresh_watchlist

    try:
        sync_state = {}
        if callable(start_background_sync):
            start_background_sync()
        refresh_all()
        watchlist_result = refresh_watchlist()
        return jsonify({
            "status": "success",
            "data": {
                "registry": watchlist_result,
                "freshness": {},
                "watchlist": watchlist_result,
            },
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/registry")
def get_registry():
    """Return the subnet registry (legacy endpoint)."""
    import json
    import os

    registry = {}
    registry_path = os.environ.get("REGISTRY_PATH", "config/registry.json")
    if os.path.exists(registry_path):
        try:
            with open(registry_path) as f:
                registry = json.load(f)
        except Exception:
            pass

    try:
        freshness = registry_freshness()
    except Exception:
        freshness = {}

    registry["freshness"] = freshness
    return jsonify(registry)


@app.route("/api/stats")
def get_stats():
    """Return dashboard stats (legacy endpoint)."""
    from internal.freshness import (
        registry_freshness as _registry_freshness,
        soul_map_freshness,
        recommendations_freshness,
        watchlist_freshness,
        overall_freshness,
    )

    try:
        freshness = {
            "registry": _registry_freshness(),
            "soul_map": soul_map_freshness(),
            "recommendations": recommendations_freshness(),
            "watchlist": watchlist_freshness(),
            "overall": overall_freshness(),
        }
    except Exception:
        freshness = {}
    return jsonify({
        "status": "success",
        "stats": {"total_subnets": 0, "active_subnets": 0},
        "freshness": freshness,
    })


@app.route("/api/learning-loop/status")
def get_learning_loop_status():
    """Return learning loop status (legacy endpoint)."""
    from internal.council.learner import LearningLoop

    learner = LearningLoop()
    result = learner.run()
    # The learner.run() already returns aligned_pct, divergent_pct, expert_weights
    return jsonify({
        "status": "success",
        "data": result,
    })


@app.route("/api/learning-loop/outcomes")
def get_learning_loop_outcomes():
    """Return learning loop outcomes (legacy endpoint)."""
    from internal.council.learner import LearningLoop

    learner = LearningLoop()
    outcomes = learner.outcomes
    limit = request.args.get("limit", 10, type=int)
    return jsonify({
        "status": "success",
        "data": outcomes[-limit:] if limit else outcomes,
    })


@app.route("/api/learning-loop/run", methods=["POST"])
def run_learning_loop():
    """Manually trigger the learning loop (legacy endpoint)."""
    from internal.council.learner import LearningLoop

    learner = LearningLoop()
    result = learner.run()
    return jsonify({
        "status": "success",
        "data": result,
    })


@app.route("/api/simivision/learning-trail")
@json_response
def get_simivision_learning_trail():
    """Return the adversarial judge's learning trail (legacy endpoint)."""
    trail = judge.get_learning_trail(limit=50)
    weights = judge.get_council_weights()
    records = judge.get_expert_track_records()
    return {
        "learning_trail": trail,
        "council_weights": weights,
        "expert_track_records": records,
    }


@app.route("/api/simivision/scheduler")
def get_simivision_scheduler():
    """Return scheduler state (legacy endpoint)."""
    return jsonify({
        "status": "success",
        "data": {
            "running": False,
            "refresh_minutes": 60,
            "backoff_minutes": 1,
            "consecutive_failures": 0,
            "last_run_at": None,
            "last_run_ok": None,
            "last_run_error": None,
            "next_run_at": None,
        },
    })


@app.route("/api/simivision/<int:subnet_id>/trace")
def get_simivision_trace(subnet_id: int):
    """Return decision trace for a specific subnet (legacy endpoint)."""
    try:
        verdicts = judge.get_verdicts(subnet_id=subnet_id, limit=20)
        weights = judge.get_council_weights()
        records = judge.get_expert_track_records()
        trail = judge.get_learning_trail(limit=50)
        return jsonify({
            "status": "success",
            "trace": {
                "council_weights": weights,
                "expert_track_records": records,
                "learning_trail": trail,
            },
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Start background tasks before serving
    _start_background_tasks()

    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)