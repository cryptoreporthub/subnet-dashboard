#!/usr/bin/env python3
"""Verify that templates/index.html compiles with Jinja2 and contains HTML."""
import os
import sys

import jinja2

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATE_PATH = os.path.join(REPO_ROOT, "templates", "index.html")

# ── 1. Jinja2 compilation check ──────────────────────────────────────────
env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.join(REPO_ROOT, "templates")),
    autoescape=False,
)
env.filters["safe_list"] = lambda x: list(x) if x is not None else []

template = env.get_template("index.html")

_default_market_intelligence = {
    "avg_change_24h": 0.0,
    "gainers": 0,
    "losers": 0,
    "total_volume": 0.0,
    "total_volume_usd": 0.0,
    "breadth": "neutral",
    "avg_apy": 0.0,
    "total_market_cap": 0.0,
    "total_market_cap_usd": 0.0,
    "total": 0,
    "top_gainer": None,
    "top_loser": None,
    "tao_price_usd": None,
}

_default_pump_analytics = {
    "status": "success",
    "data": {
        "subnets": [],
        "meta": {
            "tracked_subnets": 0,
            "total_cycles": 0,
            "avg_proneness": 0.0,
            "top_pump_candidates": [],
            "updated_at": "2025-01-01T00:00:00Z",
        },
    },
}

dummy_context = {
    "request": {},
    "data_source": "cache",
    "usd_rate": 1.0,
    "render_error": "",
    "market_intelligence": _default_market_intelligence,
    "simivision_picks": [],
    "hour_picks": [],
    "day_picks": [],
    "daily_pick": {},
    "undervalued_radar": [],
    "technical_indicators": [],
    "rotation_tracker": {},
    "pump_analytics": _default_pump_analytics,
    "patterns": [],
    "high": [],
    "pump_subnets": [],
    "audit": {"concerns": []},
}

try:
    rendered = template.render(dummy_context)
    print("✓ Jinja2 compilation successful")
except Exception as e:
    print(f"✗ Jinja2 compilation FAILED: {e}", file=sys.stderr)
    sys.exit(1)

# ── 2. Raw HTML tag check ────────────────────────────────────────────────
with open(TEMPLATE_PATH, encoding="utf-8") as f:
    raw = f.read()

if "<div" in raw or "<section" in raw:
    print("✓ Template contains HTML tags (<div> or <section>)")
else:
    print("✗ Template does not contain expected HTML tags (<div> or <section>)", file=sys.stderr)
    sys.exit(1)

print("All template checks passed.")