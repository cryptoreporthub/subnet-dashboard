"""Subnet Dashboard server package.
App factory with lifespan, scheduler startup, and route registration.
"""

import json
import logging
import os
import sys
import time
import threading
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# ---------------------------------------------------------------------------
# Config — imported from server.config (monolith header)
# ---------------------------------------------------------------------------
from server.config import (
    DATA_DIR,
    DATA_SEEDS_DIR,
    _PERSISTENT_DATA_FILES,
    _ensure_data_dir,
    # scheduler helpers
    start_indicator_scheduler,
    stop_indicator_scheduler,
    get_indicator_scheduler_state,
    # prediction resolver
    start_prediction_resolver_scheduler,
    stop_prediction_resolver_scheduler,
    get_prediction_resolver_scheduler_state,
    # picks
    select_daily_pick,
    select_hourly_pick,
    get_or_create_today_pick,
    clamp_prediction_horizon as _clamp_prediction_horizon,
    # council
    resolver,
    scenario_memory,
    rotation_tracker,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Async lifespan — starts background schedulers, seeds data on startup.
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start background services, seed data, yield, and cleanly stop schedulers."""
    logger.info("Lifespan startup: seeding data directory …")
    
    # Ensure the persistent data directory exists and is seeded from data_seeds/
    _ensure_data_dir()
    for name in _PERSISTENT_DATA_FILES:
        target = os.path.join(DATA_DIR, name)
        if os.path.exists(target) and os.path.getsize(target) > 0:
            continue
        seed = os.path.join(DATA_SEEDS_DIR, name)
        if os.path.exists(seed) and os.path.getsize(seed) > 0:
            try:
                import shutil
                shutil.copy2(seed, target)
                logger.info("Seeded %s from %s (first boot).", name, DATA_SEEDS_DIR)
            except Exception as exc:
                logger.warning("Could not seed %s: %s", name, exc)

    # Re-clamp any stale prediction horizons that used the old generic 1-168h clamp.
    try:
        from server.config import resolver as _r
        _rclamped = _r.reclamp_stored_predictions() if hasattr(_r, "reclamp_stored_predictions") else {}
        if _rclamped:
            logger.info("Re-clamped %d predictions on startup.", _rclamped.get("count", 0))
    except Exception:
        pass

    # Start background schedulers (indicator engine + prediction resolver).
    logger.info("Lifespan startup: launching background schedulers …")
    try:
        start_indicator_scheduler()
        logger.info("Indicator scheduler started.")
    except Exception as exc:
        logger.warning("Indicator scheduler did not start: %s", exc)

    try:
        start_prediction_resolver_scheduler()
        logger.info("Prediction resolver scheduler started.")
    except Exception as exc:
        logger.warning("Prediction resolver scheduler did not start: %s", exc)

    yield  # --- app runs here ---

    # Shutdown
    logger.info("Lifespan shutdown: stopping schedulers …")
    try:
        stop_indicator_scheduler()
    except Exception:
        pass
    try:
        stop_prediction_resolver_scheduler()
    except Exception:
        pass
    logger.info("Lifespan shutdown complete.")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    """Build and return the fully configured FastAPI application."""
    app = FastAPI(
        title="Subnet Dashboard",
        lifespan=_lifespan,
    )

    # --- CORS ---
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Static files & templates ---
    static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
    if os.path.isdir(static_dir):
        app.mount("/static", StaticFiles(directory="static"), name="static")
    
    templates_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
    if os.path.isdir(templates_dir):
        # Make templates available as an app state attribute for route handlers
        app.state.templates = Jinja2Templates(directory="templates")

    # --- Register all route modules ---
    from server.routes import register_routes
    register_routes(app)

    return app