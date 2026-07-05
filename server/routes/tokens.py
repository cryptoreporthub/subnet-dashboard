"""Routes: tokens."""
from fastapi import APIRouter, Request
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
from fetchers.taomarketcap import get_all_subnets, get_subnet_data
    from internal.council.state_vector import (
    from internal.council.daily_pick import select_daily_pick
    from internal.council.daily_pick_engine import get_or_create_today_pick
    from internal.council.hourly_pick import select_hourly_pick
    from internal.council import pick_history
    from internal import freshness_tracker
    from internal.council import resolver, scenario_memory, rotation_tracker
    from internal.judges import all_judges, get_judge, on_prediction_created, on_prediction_resolved
    from internal.judges.portfolios import all_portfolios
    from internal.judges.postmortems import all_postmortems, list_for_judge
    from internal.judges.subnet_judges import score_all_subnets, score_subnet
    from internal.council.weights import load_weights, save_weights
    from internal.indicators import (
    from internal.council.resolver_scheduler import (
    from datastore.learning_engine import LearningEngine
    from internal.pump_tracker import (
    from message_intel import Database as _MessageIntelDatabase
    from message_intel import NLPAnalyzer as _MessageIntelNLPAnalyzer
    from message_intel import JuryBridge as _MessageIntelJuryBridge
    from message_intel import PriceTracker as _MessageIntelPriceTracker
    from message_intel import SelfLearning as _MessageIntelSelfLearning
                import shutil
        from message_intel.telegram_listener import TelegramListener  # lazy import
            import requests
        from internal.llm.explainer import generate_ai_response

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/api/rotation-tokens")
def api_rotation_tokens_safe():
    """Return the rotation-token watchlist with live CoinGecko prices.

    Each token includes its symbol, a display label, and the current USD price
    plus 24h change fetched from CoinGecko (cached for 60 seconds).  When the
    live price feed is unavailable we fall back to the last cached value so the
    watchlist endpoint stays useful.
    """
    prices = _fetch_rotation_token_prices()
    tokens = []
    for symbol in _ROTATION_TOKENS:
        entry = prices.get(symbol, {}) if isinstance(prices, dict) else {}
        price = entry.get("price")
        change = entry.get("price_change_24h")
        tokens.append({
            "symbol": symbol.upper(),
            "name": symbol.title(),
            "price": price,
            "price_change_24h": change,
            "source": "coingecko" if price is not None else "watchlist",
        })
    return {
        "status": "success",
        "tokens": tokens,
    }



