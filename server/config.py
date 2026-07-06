Title: 

URL Source: https://raw.githubusercontent.com/cryptoreporthub/subnet-dashboard/main/server/config.py

Markdown Content:
"""Server configuration."""
import json
import logging
import math
import os
import sys
import threading
import time
import traceback
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Add the current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetchers.taomarketcap import get_all_subnets, get_subnet_data

# ---------------------------------------------------------------------------
# Safe internal imports — endpoints stay live even if modules are incomplete.
# ---------------------------------------------------------------------------
try:
    from internal.council.state_vector import (
        score_subnet_for_hour,
        score_subnet_for_day,
        clamp_prediction_horizon,
    )
except Exception:  # pragma: no cover
    def score_subnet_for_hour(*_args, **_kwargs):
        return 0.0

    def score_subnet_for_day(*_args, **_kwargs):
        return 0.0

    def clamp_prediction_horizon(horizon: int, predicted_pct: Optional[float] = None) -> int:
        """Inline fallback: HARD 4-hour maximum for every prediction horizon."""
        return max(1, min(int(horizon), 4))

# Canonical percentage-based prediction horizon clamp. Delegates to the shared
# implementation in ``internal.council.state_vector`` (with the safe fallback
# above when that module is unavailable). Apply this at every point where a
# prediction's horizon is determined, BEFORE the prediction is stored/displayed.
#
# NOTE: existing predictions already persisted with the old generic 1-168h clamp
# (e.g. a -2.1% move pinned to 168h) will keep their stale horizon until they
# either expire naturally or are re-clamped by ``_reclamp_stored_predictions``
# on startup (see ``_lifespan``).
_clamp_prediction_horizon = clamp_prediction_horizon

try:
    from internal.council.daily_pick import select_daily_pick
except Exception:  # pragma: no cover
    def select_daily_pick(*_args, **_kwargs):
        return None

try:
    from internal.council.daily_pick_engine import get_or_create_today_pick
except Exception:  # pragma: no cover
    def get_or_create_today_pick(*_args, **_kwargs):
        return {}

try:
    from internal.council.hourly_pick import select_hourly_pick
except Exception:  # pragma: no cover
    def select_hourly_pick(*_args, **_kwargs):
        return {"subnet": None, "score": 0.0, "confidence": 0.0, "expert_contributions": {}, "scenario_tags": {}, "audit": {"approved": False, "concerns": ["hourly_pick unavailable"], "adjusted_confidence": 0.0}, "final_confidence": 0.0, "action": "long"}

try:
    from internal.council import pick_history
except Exception:  # pragma: no cover
    pick_history = None  # type: ignore[assignment]

try:
    from internal import freshness_tracker
except Exception:  # pragma: no cover
    freshness_tracker = None  # type: ignore[assignment]

try:
    from internal.council import resolver, scenario_memory, rotation_tracker
except Exception:  # pragma: no cover
    class _FakeResolver:
        @staticmethod
        def resolve_due_predictions(*_args, **_kwargs):
            return {"resolved_now": [], "resolved": [], "pending": [], "stats": {}}

        @staticmethod
        def get_resolved_predictions(*_args, **_kwargs):
            return {"resolved": [], "pending": [], "stats": {}}

    resolver = _FakeResolver()
    scenario_memory = type(
        "_FakeModule",
        (),
        {
            "get_scenarios": lambda *_args, **_kwargs: [],
            "add_scenario": lambda *_args, **_kwargs: {},
            "classify_regime": lambda *_args, **_kwargs: "neutral",
            "get_memory_snapshot": lambda *_args, **_kwargs: {
                "scenarios": [],
                "regimes": {},
                "stats": {"total": 0, "by_regime": {}},
                "meta": {},
            },
        },
    )()
    rotation_tracker = type("_FakeModule", (), {"get_rotation_summary": lambda *_args, **_kwargs: {}})()

try:
    from internal.judges import all_judges, get_judge, on_prediction_created, on_prediction_resolved
    from internal.judges.portfolios import all_portfolios
    from internal.judges.postmortems import all_postmortems, list_for_judge
    _JUDGES_AVAILABLE = True
except Exception as _judges_import_exc:  # pragma: no cover
    _JUDGES_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("Judge layer unavailable: %s", _judges_import_exc)

    def all_judges():
        return []

    def get_judge(name):
        return None

    def on_prediction_created(*_args, **_kwargs):
        return {}

    def on_prediction_resolved(*_args, **_kwargs):
        return {}

    def all_portfolios():
        return {}

    def all_postmortems():
        return {}

    def list_for_judge(name):
        return []

# Per-subnet judge scoring (new council surface). Safe fallback keeps the app
# booting even if the module is incomplete or its dependencies are missing.
try:
    from internal.judges.subnet_judges import score_all_subnets, score_subnet
    _SUBNET_JUDGES_AVAILABLE = True
except Exception as _subnet_judges_import_exc:  # pragma: no cover
    _SUBNET_JUDGES_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("Subnet judge layer unavailable: %s", _subnet_judges_import_exc)

    def score_all_subnets(*_args, **_kwargs):
        return []

    def score_subnet(*_args, **_kwargs):
        return {}

try:
    from internal.council.weights import load_weights, save_weights
except Exception:  # pragma: no cover
    _DEFAULT_WEIGHTS = {"quant": 1.0, "hype": 1.0, "contrarian": 1.0, "technical": 1.0}

    def load_weights(*_args, **_kwargs):
        return dict(_DEFAULT_WEIGHTS)

    def save_weights(*_args, **_kwargs):
        pass

try:
    from internal.indicators import (
        IndicatorEngine,
        get_indicator_scheduler_state,
        start_indicator_scheduler,
        stop_indicator_scheduler,
    )
except Exception:  # pragma: no cover
    class IndicatorEngine:
        pass

    def get_indicator_scheduler_state(*_args, **_kwargs):
        return {"running": False}

    def start_indicator_scheduler(*_args, **_kwargs):
        pass

    def stop_indicator_scheduler(*_args, **_kwargs):
        pass

# Prediction resolver scheduler — grades pending predictions on a clock so the
# learning loop's weights/accuracy update even when no dashboard is rendered.
try:
    from internal.council.resolver_scheduler import (
        get_prediction_resolver_scheduler,
        get_prediction_resolver_scheduler_state,
        start_prediction_resolver_scheduler,
        stop_prediction_resolver_scheduler,
    )
except Exception:  # pragma: no cover
    def get_prediction_resolver_scheduler_state(*_args, **_kwargs):
        return {"running": False}

    def start_prediction_resolver_scheduler(*_args, **_kwargs):
        pass

    def stop_prediction_resolver_scheduler(*_args, **_kwargs):
        pass

    def get_prediction_resolver_scheduler(*_args, **_kwargs):
        return None

try:
    from datastore.learning_engine import LearningEngine
except Exception:  # pragma: no cover
    class LearningEngine:
        def __init__(self, *args, **kwargs):
            pass

try:
    from internal.pump_tracker import (
        get_pump_tracker,
        get_all_profiles,
        get_current_phases,
        get_recent_cycles,
        get_cycle_analytics_accuracy,
        get_pump_tracker_state,
    )
    _PUMP_TRACKER_AVAILABLE = True
except Exception:  # pragma: no cover
    _PUMP_TRACKER_AVAILABLE = False

    def get_pump_tracker(*_args, **_kwargs):
        return None

    def get_all_profiles(*_args, **_kwargs):  # type: ignore[no-redef]
        return {}

    def get_current_phases(*_args, **_kwargs):  # type: ignore[no-redef]
        return {}

    def get_recent_cycles(*_args, **_kwargs):  # type: ignore[no-redef]
        return []

    def get_cycle_analytics_accuracy(*_args, **_kwargs):  # type: ignore[no-redef]
        return {"status": "success", "accuracy": {}}

    def get_pump_tracker_state(*_args, **_kwargs):  # type: ignore[no-redef]
        return {"status": "error", "error": "pump tracker unavailable"}

try:
    from message_intel import Database as _MessageIntelDatabase
    from message_intel import NLPAnalyzer as _MessageIntelNLPAnalyzer
    from message_intel import JuryBridge as _MessageIntelJuryBridge
    from message_intel import PriceTracker as _MessageIntelPriceTracker
    from message_intel import SelfLearning as _MessageIntelSelfLearning
    _MESSAGE_INTEL_AVAILABLE = True
except Exception as _message_intel_import_exc:
    _MESSAGE_INTEL_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("Message intelligence package unavailable: %s", _message_intel_import_exc)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

# Runtime data directory. In production this is a Fly.io persistent volume
# mount point (see fly.toml [mounts]); locally it is just ./data. The directory
# is created on startup so the app works with or without a mounted volume.
DATA_DIR = os.environ.get("DATA_DIR", "data")
DATA_SEEDS_DIR = os.environ.get("DATA_SEEDS_DIR", "data_seeds")
# Learning-critical files that should survive deploys. On the first boot of an
# empty volume these are seeded from data_seeds/ so prior learning is preserved;
# they are never overwritten once present on the volume.
_PERSISTENT_DATA_FILES = ("predictions.json", "soul_map.json")

def _ensure_data_dir() -> None:
    """Create the data directory if missing and diagnose persistence state.

    - Ensures ``DATA_DIR`` exists (works with or without a Fly volume).
    - Seeds learning-critical files from ``DATA_SEEDS_DIR`` when the volume is
      empty on first boot (never overwrites existing data).
    - Logs a warning for each missing/empty persistent file so future resets
      are diagnosable from the app logs.
    """
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except Exception as exc:
        logger.warning("Could not create data directory %s: %s", DATA_DIR, exc)
        return

    # Seed missing learning-critical files from packaged defaults so an empty
    # volume does not silently discard prior learning on first boot.
    for name in _PERSISTENT_DATA_FILES:
        target = os.path.join(DATA_DIR, name)
        if os.path.exists(target) and os.path.getsize(target) > 0:
            continue
        seed = os.path.join(DATA_SEEDS_DIR, name)
        if os.path.exists(seed) and os.path.getsize(seed) > 0:
            try:
                import shutil

                shutil.copy2(seed, target)
                logger.info(
                    "Seeded empty/missing data file %s from %s (first boot of "
                    "persistent volume).", name, DATA_SEEDS_DIR
                )
            except Exception as exc:
                logger.warning("Could not seed %s from %s: %s", name, seed, exc)

    # Diagnostic logging: surface missing/empty persistent files so future
    # learning-data resets are visible in the app logs.
    for name in _PERSISTENT_DATA_FILES:
        path = os.path.join(DATA_DIR, name)
        try:
            if not os.path.exists(path):
                logger.warning(
                    "Learning data file missing on startup: %s "
                    "(data may have been reset or the volume is empty).", path
                )
            elif os.path.getsize(path) == 0:
                logger.warning(
       

[read_links truncated 22986 chars from this runtime tool output. The full content is stored with the tool result.]