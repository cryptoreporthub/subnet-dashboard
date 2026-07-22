import json
import logging
import os
import asyncio
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.sentry_setup import init_sentry

init_sentry()

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from internal.council.mindmap_bridge import MindmapBridge
from internal.rate_limit import limit_or_noop, mount_rate_limit, strict_limit
from internal.whales.routes import whales_router
from internal.watchlist.routes import watchlist_router
from internal.portfolio.routes import portfolio_router
from internal.letter.routes import letter_router

logger = logging.getLogger("server")

try:
    from internal.judges.council_routes import council_router

    _COUNCIL_ROUTES = True
except Exception as _council_exc:  # pragma: no cover - defensive import guard
    logger.warning("Council judge routes unavailable: %s", _council_exc)
    _COUNCIL_ROUTES = False

try:
    from internal.learning.routes import learning_router

    _LEARNING_ROUTES = True
except Exception as _learning_exc:  # pragma: no cover - defensive import guard
    logger.warning("Learning loop routes unavailable: %s", _learning_exc)
    _LEARNING_ROUTES = False

try:
    from internal.simivision.routes import simivision_router

    _SIMIVISION_ROUTES = True
except Exception as _simivision_exc:  # pragma: no cover - defensive import guard
    logger.warning("SimiVision routes unavailable: %s", _simivision_exc)
    _SIMIVISION_ROUTES = False

try:
    from internal.ruggers.routes import ruggers_router

    _RUGGERS_ROUTES = True
except Exception as _ruggers_exc:  # pragma: no cover - defensive import guard
    logger.warning("Ruggers watchlist routes unavailable: %s", _ruggers_exc)
    _RUGGERS_ROUTES = False

try:
    from internal.indicators.routes import indicators_router

    _INDICATORS_ROUTES = True
except Exception as _indicators_exc:  # pragma: no cover - defensive import guard
    logger.warning("Indicator routes unavailable: %s", _indicators_exc)
    _INDICATORS_ROUTES = False

try:
    from internal.oracle.routes import oracle_router

    _ORACLE_ROUTES = True
except Exception as _oracle_exc:  # pragma: no cover - defensive import guard
    logger.warning("Oracle routes unavailable: %s", _oracle_exc)
    _ORACLE_ROUTES = False

try:
    from internal.analytics.routes import analytics_router

    _ANALYTICS_ROUTES = True
except Exception as _analytics_exc:  # pragma: no cover - defensive import guard
    logger.warning("Analytics routes unavailable: %s", _analytics_exc)
    _ANALYTICS_ROUTES = False

try:
    from internal.health.routes import health_router

    _HEALTH_ROUTES = True
except Exception as _health_exc:  # pragma: no cover - defensive import guard
    logger.warning("Health routes unavailable: %s", _health_exc)
    _HEALTH_ROUTES = False

try:
    from internal.investigation import investigation_router

    _INVESTIGATION_ROUTES = True
except Exception as _investigation_exc:  # pragma: no cover
    logger.warning("Investigation routes unavailable: %s", _investigation_exc)
    investigation_router = None  # type: ignore[assignment,misc]
    _INVESTIGATION_ROUTES = False

try:
    from internal.share_pages.routes import share_router

    _SHARE_ROUTES = True
except Exception as _share_exc:  # pragma: no cover
    logger.warning("Share page routes unavailable: %s", _share_exc)
    share_router = None  # type: ignore[assignment,misc]
    _SHARE_ROUTES = False

try:
    from internal.cockpit import cockpit_router

    _COCKPIT_ROUTES = cockpit_router is not None
except Exception as _cockpit_exc:  # pragma: no cover - defensive import guard
    logger.warning("Cockpit routes unavailable: %s", _cockpit_exc)
    cockpit_router = None  # type: ignore[assignment,misc]
    _COCKPIT_ROUTES = False

try:
    from internal.analytics.store_routes import store_router

    _STORE_ROUTES = True
except Exception as _store_exc:  # pragma: no cover - defensive import guard
    logger.warning("Store routes unavailable: %s", _store_exc)
    _STORE_ROUTES = False

try:
    from internal.mindmap import mindmap_graph_router

    _MINDMAP_GRAPH_ROUTES = mindmap_graph_router is not None
except Exception as _mindmap_graph_exc:  # pragma: no cover - defensive import guard
    logger.warning("Mindmap graph routes unavailable: %s", _mindmap_graph_exc)
    mindmap_graph_router = None  # type: ignore[assignment,misc]
    _MINDMAP_GRAPH_ROUTES = False

try:
    from internal.signals import signals_router

    _SIGNALS_ROUTES = True
except Exception as _signals_exc:  # pragma: no cover - defensive import guard
    logger.warning("Signals routes unavailable: %s", _signals_exc)
    signals_router = None  # type: ignore[assignment,misc]
    _SIGNALS_ROUTES = False

# Council pick engine (guarded so a broken/missing engine module can never stop
# the app from booting — the picks endpoints degrade to a safe fallback).
try:
    from fetchers.taomarketcap import get_all_subnets
    from internal.council.state_vector import (
        score_subnet_for_hour,
        score_subnet_for_day,
    )
    from internal.council.hourly_pick import select_hourly_pick
    from internal.council.daily_pick_engine import get_or_create_today_pick

    _PICKS_ENGINE = True
except Exception as _exc:  # pragma: no cover - defensive import guard
    logger.warning("Pick engine unavailable, using fallbacks: %s", _exc)
    _PICKS_ENGINE = False

try:
    from internal.council.weights import effective_weights, load_weights
except Exception:
    def load_weights():  # type: ignore
        return {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}

    def effective_weights(market_data=None, path=None):  # type: ignore
        return load_weights()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Boot background workers on web only when BACKGROUND_ON_WEB=on (legacy/combined)."""
    from internal.run_mode import background_on_web, is_worker_mode

    if is_worker_mode():
        yield
        return

    # Never block lifespan on Jinja — Fly health checks fail and edge returns 0 bytes.
    if not is_worker_mode():
        threading.Thread(
            target=_prime_emergency_home_html,
            daemon=True,
            name="emergency-prime",
        ).start()
        threading.Thread(
            target=lambda: _warm_homepage_cache(None),
            daemon=True,
            name="homepage-warm-boot",
        ).start()

    if background_on_web():
        from internal.background_boot import start_background_workers, stop_background_workers

        start_background_workers()
    yield
    if background_on_web():
        from internal.background_boot import stop_background_workers

        stop_background_workers()
    try:
        from internal.http_client import close_async_client

        await close_async_client()
    except Exception:
        pass


app = FastAPI(title="Subnet Dashboard", lifespan=_lifespan)

try:
    from internal.load_shed import mount_load_shed

    mount_load_shed(app)
except Exception as _load_shed_exc:  # pragma: no cover
    logger.warning("Load shed middleware unavailable: %s", _load_shed_exc)

_ENABLE_METRICS = os.environ.get("ENABLE_METRICS", "1").strip().lower() not in ("0", "false", "no")
if _ENABLE_METRICS:
    try:
        from prometheusrock import PrometheusMiddleware

        from internal.metrics import metrics_endpoint

        app.add_middleware(
            PrometheusMiddleware,
            app_name="subnet_dashboard",
            remove_labels=["headers"],
            skip_paths=["/metrics", "/health", "/api/health"],
        )
        app.add_route("/metrics", metrics_endpoint)
    except Exception as exc:
        logger.warning("Prometheus metrics unavailable: %s", exc)

mount_rate_limit(app)

app.include_router(whales_router)
app.include_router(watchlist_router)
app.include_router(portfolio_router)
app.include_router(letter_router)
if _COUNCIL_ROUTES:
    app.include_router(council_router)
if _LEARNING_ROUTES:
    app.include_router(learning_router)
if _SIMIVISION_ROUTES:
    app.include_router(simivision_router)
if _RUGGERS_ROUTES:
    app.include_router(ruggers_router)
if _INDICATORS_ROUTES:
    app.include_router(indicators_router)
if _ORACLE_ROUTES:
    app.include_router(oracle_router)
if _ANALYTICS_ROUTES:
    app.include_router(analytics_router)
if _HEALTH_ROUTES:
    app.include_router(health_router)
if _COCKPIT_ROUTES:
    app.include_router(cockpit_router)
if _STORE_ROUTES:
    app.include_router(store_router)
if _MINDMAP_GRAPH_ROUTES:
    app.include_router(mindmap_graph_router)
if _SIGNALS_ROUTES:
    app.include_router(signals_router)
if _INVESTIGATION_ROUTES:
    app.include_router(investigation_router)
if _SHARE_ROUTES:
    app.include_router(share_router)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


def _jinja_safe_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        return list(value)
    except TypeError:
        return []


def _jinja_shorten(value: Any, places: int = 1) -> str:
    """Compact numeric display for volumes (e.g. 1.2M, 340K)."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    if n >= 1e9:
        return f"{n / 1e9:.{places}f}B"
    if n >= 1e6:
        return f"{n / 1e6:.{places}f}M"
    if n >= 1e3:
        return f"{n / 1e3:.{places}f}K"
    return f"{n:.{places}f}"


templates.env.filters["safe_list"] = _jinja_safe_list
templates.env.filters["shorten"] = _jinja_shorten

_static_dir = os.path.join(BASE_DIR, "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# Paths that get a short public cache to keep the dashboard snappy on Fly.io.
_CACHE_PATHS = {
    "/api/registry": 30,
    "/api/summary": 30,
    "/api/stats": 30,
    "/api/subnets": 300,
    "/api/council": 120,
    "/api/judges": 120,
    "/api/search": 60,
    "/api/learning-metrics": 60,
    "/api/learning/stats": 60,
}


def load_data(filename):
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return json.load(f)
    return {}


from internal.subnets.feed import load_subnets_source, subnet_feed_meta as _subnet_feed_meta


def _tag_subnet_row(row: Dict[str, Any], feed_meta: Dict[str, Any]) -> Dict[str, Any]:
    """Attach honest source labels to a subnet row."""
    item = dict(row)
    primary = str(item.get("source") or feed_meta.get("source") or "registry").lower()
    if item.get("live") and primary != "blockmachine":
        primary = "blockmachine"
    item["source"] = primary
    sources = item.get("sources")
    if not isinstance(sources, list) or not sources:
        if primary == "blockmachine":
            item["sources"] = list(feed_meta.get("sources") or ["blockmachine"])
        else:
            item["sources"] = [primary]
    return item


def _consensus_map():
    """Build a subnet_id -> consensus decision lookup from the latest soul-map output."""
    soul_map = load_data("data/soul_map.json")
    last_output = soul_map.get("soul_map_state", {}).get("last_selector_output", {})
    decisions = last_output.get("decisions", [])
    return {d["subnet_id"]: d for d in decisions if "subnet_id" in d}


# audit #11: scoped CORS + valid X-Frame-Options (see docs/EXTREME_AUDIT.md #11)
_ALLOWED_ORIGINS = frozenset(
    o.strip()
    for o in os.environ.get("ALLOWED_ORIGINS", "https://subnet-dashboard.fly.dev").split(",")
    if o.strip()
)


@app.middleware("http")
async def add_cors_headers(request: Request, call_next):
    """Allow dashboard embedding and cross-origin API access (parity with prior Flask behavior)."""
    response = await call_next(request)
    origin = request.headers.get("origin")
    if origin and origin in _ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    path = request.url.path
    cache_ttl = _CACHE_PATHS.get(path)
    if cache_ttl is None:
        for prefix, ttl in _CACHE_PATHS.items():
            if path.startswith(prefix + "/") or path == prefix:
                cache_ttl = ttl
                break
    if cache_ttl is not None:
        response.headers["Cache-Control"] = f"public, max-age={cache_ttl}"
    elif path.startswith("/static/"):
        if path.endswith((".js", ".css")):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "public, max-age=3600"
    return response


HOMEPAGE_BUILD_TIMEOUT = int(os.environ.get("HOMEPAGE_BUILD_TIMEOUT", "12"))
HOMEPAGE_SHELL_CACHE_SECONDS = float(os.environ.get("HOMEPAGE_SHELL_CACHE_SECONDS", "45"))
TOP_SCORING_UNIVERSE = int(os.environ.get("TOP_SCORING_UNIVERSE", "40"))
_DEGRADED_INDEX_CACHE: Dict[str, Any] = {"at": 0.0, "ctx": None}
_HOMEPAGE_HTML_CACHE: Dict[str, Any] = {"at": 0.0, "html": None}
_EMERGENCY_HOME_HTML: str = ""
_HOMEPAGE_WARM_LOCK = threading.Lock()
_HOMEPAGE_WARMING = False


class _HomepageStubRequest:
    """Minimal Request stand-in for offline homepage renders."""

    @property
    def base_url(self):
        from starlette.datastructures import URL

        explicit = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
        return URL((explicit or "http://localhost") + "/")


def _prime_emergency_home_html() -> str:
    """One-time render of the minimal shell — served instantly on cache miss."""
    global _EMERGENCY_HOME_HTML
    if _EMERGENCY_HOME_HTML:
        return _EMERGENCY_HOME_HTML
    ctx = _minimal_index_context(_HomepageStubRequest())
    _EMERGENCY_HOME_HTML = templates.get_template("index.html").render(ctx)
    return _EMERGENCY_HOME_HTML


def _render_index_html(request: Request) -> str:
    ctx = _degraded_index_context(request)
    return templates.get_template("index.html").render(ctx)


def _warm_homepage_cache(request: Optional[Request] = None) -> None:
    """Build degraded homepage HTML off the request hot path."""
    global _HOMEPAGE_WARMING
    now = time.time()
    cached_html = _HOMEPAGE_HTML_CACHE.get("html")
    if (
        isinstance(cached_html, str)
        and cached_html
        and now - float(_HOMEPAGE_HTML_CACHE.get("at") or 0) < HOMEPAGE_SHELL_CACHE_SECONDS
    ):
        return
    with _HOMEPAGE_WARM_LOCK:
        if _HOMEPAGE_WARMING:
            return
        _HOMEPAGE_WARMING = True
    try:
        req: Any = request if request is not None else _HomepageStubRequest()
        html = _render_index_html(req)
        _HOMEPAGE_HTML_CACHE["html"] = html
        _HOMEPAGE_HTML_CACHE["at"] = time.time()
    except Exception as exc:
        logger.warning("homepage cache warm failed: %s", exc)
    finally:
        with _HOMEPAGE_WARM_LOCK:
            _HOMEPAGE_WARMING = False


def _cap_subnets_for_scoring(
    subnets: List[Dict[str, Any]],
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Limit council scoring to the most active subnets (Fly single-worker safety).

    Prefer live-priced market activity (volume, market_cap) when present; fall
    back to emission so registry-only snapshots still produce a stable universe.
    Unpriced emission-only rows rank below any row with a positive price.
    """
    from internal.subnets.tradable import subnet_volume

    cap = limit if limit is not None else TOP_SCORING_UNIVERSE
    if not subnets or len(subnets) <= cap:
        return subnets

    def _has_price(s: Dict[str, Any]) -> int:
        try:
            return 1 if float(s.get("price") or 0) > 0 else 0
        except (TypeError, ValueError):
            return 0

    def _rank_key(s: Dict[str, Any]):
        vol = subnet_volume(s)
        mcap = float(s.get("market_cap", 0) or 0)
        emission = float(s.get("emission", 0) or 0)
        mcr = s.get("marketcap_rank")
        try:
            # Lower marketcap_rank is better when present and positive.
            rank_bonus = -int(mcr) if mcr not in (None, "", 0, "0") else 0
        except (TypeError, ValueError):
            rank_bonus = 0
        priced = _has_price(s)
        if vol > 0 or mcap > 0:
            return (priced, 1, vol, mcap, rank_bonus, emission)
        return (priced, 0, 0.0, 0.0, 0, emission)

    return sorted(subnets, key=_rank_key, reverse=True)[:cap]


def _normalize_registry_subnet(sn: Dict[str, Any]) -> Dict[str, Any]:
    """Registry rows use ``id``; ensure ``netuid`` and canonical name."""
    row = dict(sn)
    if row.get("netuid") is None and row.get("id") is not None:
        row["netuid"] = row["id"]
    try:
        from internal.subnet_names import enrich_subnet_row

        return enrich_subnet_row(row, use_taostats=False)
    except Exception:
        name = str(row.get("name") or "")
        if name.lower() in ("deprecated", "unknown", "none", ""):
            row["name"] = f"SN{row.get('netuid', row.get('id', '?'))}"
        return row


def _quiet_brain_letter_stub() -> Dict[str, Any]:
    """Instant Quiet SSR — hydrate fills via /api/letter/brain."""
    return {
        "brain_letter": {
            "status": "quiet",
            "empty": True,
            "date": None,
            "outlook": "No sized call this window — watching the desk into resolve.",
        }
    }


def _safe_brain_letter_context(*, timeout_s: float = 1.5) -> Dict[str, Any]:
    """Timeboxed letter SSR — never block GET / past timeout_s."""
    import concurrent.futures

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        from internal.letter.brain_letter import build_brain_letter

        fut = pool.submit(build_brain_letter)
        return {"brain_letter": fut.result(timeout=timeout_s)}
    except Exception as exc:
        logger.warning("brain letter context skipped: %s", exc)
        return _quiet_brain_letter_stub()
    finally:
        # wait=False: timed-out builder must not hold the request open
        pool.shutdown(wait=False, cancel_futures=True)


def _fast_home_hero_context(trust_banner: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Cheap hero keys for degraded GET / — no pick engine or resolver replay."""
    from internal.analytics.home_habit import (
        conviction_alerts_snapshot,
        watchlist_snapshot,
    )

    tb = trust_banner if isinstance(trust_banner, dict) else {}
    return {
        "daily_pick_stage": {},
        "conviction_band": {"band": None, "reason": "hydrate", "status": "ok"},
        "enrichment_badge": {"status": "pending"},
        "story_strip": {
            "data_available": False,
            "reason": "hydrate",
            "items": [],
            "stats": {"correct": 0, "wrong": 0},
        },
        "habit_watchlist": watchlist_snapshot(),
        "habit_alerts": conviction_alerts_snapshot(),
        "hybrid_trust": {
            "status": "ok",
            "ready": bool(tb.get("ready")),
            "n": tb.get("graded") or 0,
            "min_sample": 30,
            "accuracy": tb.get("accuracy"),
            "correct": tb.get("correct"),
            "wrong": tb.get("wrong"),
        },
        "trust_banner": tb,
    }


def _enrich_daily_pick_payload_lite(
    pick_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Fast read path for GET /api/daily-pick — no subnet scoring or live feeds."""
    if not isinstance(pick_payload, dict):
        return {}
    from internal.learning.dpick_copy import attach_brief_to_daily_pick
    from internal.learning.dpick_pump import attach_pump_chip_to_daily_pick
    from internal.learning.dpick_temporal import attach_temporal_to_daily_pick
    from internal.subnet_names import refresh_daily_pick_names

    out = refresh_daily_pick_names(pick_payload)
    out = attach_temporal_to_daily_pick(out)
    out = attach_brief_to_daily_pick(out)
    if "shortlist" not in out:
        out["shortlist"] = []
    if not isinstance(out.get("horizon_views"), dict):
        out["horizon_views"] = {"default": "24h", "anchor": "24h", "chips": [], "views": {}}
        out["horizon_active"] = "24h"
    return attach_pump_chip_to_daily_pick(out, [])


def _enrich_daily_pick_payload(
    pick_payload: Optional[Dict[str, Any]],
    subnets: List[Dict[str, Any]],
    market_context: Dict[str, Any],
) -> Dict[str, Any]:
    """Names, shortlist, temporal, horizon, K3-7 brief, and K3-7b pump chip."""
    if not isinstance(pick_payload, dict):
        return {}
    from internal.learning.dpick_copy import attach_brief_to_daily_pick
    from internal.learning.dpick_horizon import attach_horizon_views_to_daily_pick
    from internal.learning.dpick_pump import attach_pump_chip_to_daily_pick
    from internal.learning.dpick_shortlist import attach_shortlist_to_daily_pick
    from internal.learning.dpick_temporal import attach_temporal_to_daily_pick
    from internal.subnet_names import refresh_daily_pick_names

    out = refresh_daily_pick_names(pick_payload)
    out = attach_shortlist_to_daily_pick(out, subnets, market_context)
    out = attach_temporal_to_daily_pick(out)
    out = attach_horizon_views_to_daily_pick(out, subnets, market_context)
    out = attach_brief_to_daily_pick(out)
    return attach_pump_chip_to_daily_pick(out, subnets)


def _home_hero_context(subnets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """U1 hero keys for GET / (fast shell + hydrate)."""
    from internal.analytics.home_habit import (
        conviction_alerts_snapshot,
        hybrid_trust_snapshot,
        watchlist_snapshot,
    )
    from internal.analytics.root_context import (
        _safe_conviction_band,
        _safe_enrichment_badge,
        _safe_story_strip,
        _safe_trust_banner,
    )

    pick_payload: Optional[Dict[str, Any]] = None
    pick_netuid: Optional[int] = None
    try:
        if _PICKS_ENGINE:
            market_context = _market_context_with_weights(subnets)
            pick_payload = get_or_create_today_pick(subnets, market_context)
            pick_netuid = _pick_netuid_from_daily_payload(pick_payload)
            if isinstance(pick_payload, dict):
                pick_payload = _enrich_daily_pick_payload(
                    pick_payload, subnets, market_context
                )
    except Exception as exc:
        logger.warning("home hero context failed: %s", exc)
    story_path: Dict[str, Any] = {}
    try:
        from internal.learning.story_path import build_story_path

        if isinstance(pick_payload, dict) and pick_payload:
            story_path = build_story_path(pick_payload)
    except Exception as exc:
        logger.warning("story path context failed: %s", exc)
    hero = {
        "daily_pick_stage": pick_payload if isinstance(pick_payload, dict) else {},
        "conviction_band": _safe_conviction_band(pick_payload),
        "enrichment_badge": _safe_enrichment_badge(pick_netuid),
        "story_strip": _safe_story_strip(),
        "habit_watchlist": watchlist_snapshot(),
        "habit_alerts": conviction_alerts_snapshot(),
        "hybrid_trust": hybrid_trust_snapshot(),
        "trust_banner": _safe_trust_banner(),
        "story_path": story_path,
    }
    hero.update(_safe_brain_letter_context())
    return hero


def _public_base_url(request: Request) -> str:
    """Canonical public URL (APP_BASE_URL override, else request host)."""
    explicit = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    return str(request.base_url).rstrip("/")


def _pump_alerts_context(subnets: List[Dict[str, Any]]) -> Dict[str, Any]:
    try:
        from internal.learning.pump_alert import build_pump_alerts

        return {"pump_alerts": build_pump_alerts(subnets)}
    except Exception as exc:
        logger.warning("pump alerts context failed: %s", exc)
        return {
            "pump_alerts": {
                "status": "unavailable",
                "count": 0,
                "alerts": [],
                "empty_message": (
                    "No names in PUMPING right now. Early heat stays on the dossier chip when the lead is warming."
                ),
                "error": str(exc),
            }
        }


def _degraded_index_context(request: Request) -> Dict[str, Any]:
    """Fast shell — registry subnets + local learning state; hydrate upgrades live APIs."""
    now = time.time()
    cached = _DEGRADED_INDEX_CACHE.get("ctx")
    if isinstance(cached, dict) and now - float(_DEGRADED_INDEX_CACHE.get("at") or 0) < HOMEPAGE_SHELL_CACHE_SECONDS:
        ctx = dict(cached)
        ctx["request"] = request
        ctx["public_base_url"] = _public_base_url(request)
        return ctx

    from internal.learning.dashboard_context import fast_shell_dashboard_context
    from internal.subnet_names import enrich_subnet_rows

    subnets = enrich_subnet_rows(list(load_data("config/registry.json").values()))
    # Market drawer is demoted — don't Jinja-loop 128 rows on the hot path.
    # Hydrate + Market drawer APIs fill scanner/staking after first paint.
    shell_subnets = _cap_subnets_for_scoring(subnets, limit=min(24, TOP_SCORING_UNIVERSE))
    shell_learning = fast_shell_dashboard_context()
    simivision_data = _safe_simivision_payload(
        subnets=shell_subnets, source="registry-fallback"
    ).get("data", {"top": [], "meta": {"count": len(shell_subnets), "source": "registry-fallback"}})
    trust_banner = (shell_learning.get("learning_metrics") or {}).get("trust_banner") or {}
    ctx = {
        "request": request,
        "public_base_url": _public_base_url(request),
        "subnets": [],  # empty market SSR — hydrate owns the warehouse
        "data_source": "snapshot",
        "degraded": True,
        **shell_learning,
        "simivision": simivision_data,
        "signals": [],
        "alerts": [],
        "signal_summary": {
            "total_subnets": 0,
            "buy_count": 0,
            "sell_count": 0,
            "neutral_count": 0,
            "buy_sell_ratio": 0.0,
            "avg_confidence": 0.0,
        },
    }
    ctx.update(_fast_home_hero_context(trust_banner))
    # Letter + pump hydrate client-side — keep cold shell off the hang path
    ctx.update(_quiet_brain_letter_stub())
    ctx["pump_alerts"] = {
        "status": "quiet",
        "count": 0,
        "alerts": [],
        "empty_message": "Pump desk loads after hydrate.",
    }
    stash = {k: v for k, v in ctx.items() if k != "request"}
    _DEGRADED_INDEX_CACHE["at"] = now
    _DEGRADED_INDEX_CACHE["ctx"] = stash
    return ctx


def _minimal_index_context(request: Request) -> Dict[str, Any]:
    """Emergency shell when homepage build exceeds HOMEPAGE_BUILD_TIMEOUT.

    Must stay instant — no letter build, no pump scan. Blank-screen root cause
    on Fly is 0-byte proxy timeout when this path also hangs.
    """
    from internal.learning.dashboard_context import fast_shell_dashboard_context

    shell_learning = fast_shell_dashboard_context()
    trust_banner = (shell_learning.get("learning_metrics") or {}).get("trust_banner") or {}
    return {
        "request": request,
        "public_base_url": _public_base_url(request),
        "subnets": [],
        "data_source": "snapshot",
        "degraded": True,
        **shell_learning,
        "simivision": {"top": [], "meta": {"count": 0, "source": "timeout-fallback"}},
        "signals": [],
        "alerts": [],
        "signal_summary": {
            "total_subnets": 0,
            "buy_count": 0,
            "sell_count": 0,
            "neutral_count": 0,
            "buy_sell_ratio": 0.0,
            "avg_confidence": 0.0,
        },
        **_fast_home_hero_context(trust_banner),
        **_quiet_brain_letter_stub(),
        "pump_alerts": {
            "status": "quiet",
            "count": 0,
            "alerts": [],
            "empty_message": "Pump desk quiet — retry after hydrate.",
        },
    }


def _build_index_context(request: Request) -> Dict[str, Any]:
    subnets, source = _get_subnets_with_source()
    market_context = {"tao_change_24h": _market_mood_proxy(subnets)}

    # --- Agent A slice 12a: learning/council/freshness dashboard context ---
    learning_ctx = {}
    try:
        from internal.learning.dashboard_context import (
            build_learning_dashboard_context,
            default_learning_dashboard_context,
        )

        learning_ctx = build_learning_dashboard_context(subnets, market_context)
    except Exception as exc:
        logger.warning("slice 12a learning dashboard context failed: %s", exc)
        from internal.learning.dashboard_context import default_learning_dashboard_context

        learning_ctx = default_learning_dashboard_context()

    context = {
        "request": request,
        "subnets": subnets,
        "data_source": source,
        **learning_ctx,
    }

    # slice 12b — Agent B root context (owned modules only)
    try:
        from internal.analytics.root_context import build_agent_b_root_context

        context.update(_home_hero_context(subnets))
        context.update(
            build_agent_b_root_context(
                subnets=subnets,
                data_source=source,
                pick_netuid=_pick_netuid_from_daily_payload(context.get("daily_pick_stage")),
                daily_pick_payload=context.get("daily_pick_stage"),
            )
        )
    except Exception as exc:
        logger.warning("Agent B root context unavailable: %s", exc)

    try:
        from internal.analytics.cockpit_render import load_cockpit_sections

        context["cockpit_sections"] = load_cockpit_sections()
    except Exception as exc:
        logger.warning("Cockpit sections unavailable: %s", exc)

    try:
        context["simivision"] = _safe_simivision_payload(
            subnets=subnets,
            source=source,
            daily_pick=context.get("daily_pick_stage")
            if isinstance(context.get("daily_pick_stage"), dict)
            else None,
            market_context=market_context,
        ).get("data", {})
    except Exception as exc:
        logger.warning("SimiVision context unavailable: %s", exc)
        context["simivision"] = {"top": [], "meta": {"count": 0}}

    try:
        from internal.message_intel.context import build_message_intel_context

        context.update(build_message_intel_context(subnets))
    except Exception as exc:
        logger.warning("Message intel context unavailable: %s", exc)

    # Phase L — signals/alerts Jinja context (server.py glue only)
    try:
        from internal.signals.context import build_signals_context

        context.update(build_signals_context(refresh=False))
    except Exception as exc:
        logger.warning("Signals context unavailable: %s", exc)

    # Phase O — signal hub Jinja context (server.py glue only)
    try:
        from internal.signal_hub.context import build_signal_hub_context

        context.update(build_signal_hub_context())
    except Exception as exc:
        logger.warning("Signal hub context unavailable: %s", exc)

    context.update(_pump_alerts_context(subnets))

    return context


def _bailout_homepage_html() -> Optional[str]:
    """HTML for ASGI bailout — warm cache on miss, then Jinja emergency, else hardcoded."""
    now = time.time()
    cached_html = _HOMEPAGE_HTML_CACHE.get("html")
    if (
        isinstance(cached_html, str)
        and cached_html
        and now - float(_HOMEPAGE_HTML_CACHE.get("at") or 0) < HOMEPAGE_SHELL_CACHE_SECONDS
    ):
        return cached_html
    _schedule_homepage_warm(None)
    try:
        return _prime_emergency_home_html()
    except Exception as exc:
        logger.warning("bailout emergency prime failed: %s", exc)
        return None


def _schedule_homepage_warm(request: Optional[Request] = None) -> None:
    """Fire-and-forget warm — must not block GET / (TestClient runs BackgroundTasks inline)."""
    threading.Thread(
        target=_warm_homepage_cache,
        args=(request,),
        daemon=True,
        name="homepage-warm",
    ).start()


@app.get("/")
async def index(request: Request):
    """Instant shell on cache miss — never block the Starlette thread pool on Jinja."""
    from fastapi.responses import HTMLResponse

    now = time.time()
    cached_html = _HOMEPAGE_HTML_CACHE.get("html")
    if (
        isinstance(cached_html, str)
        and cached_html
        and now - float(_HOMEPAGE_HTML_CACHE.get("at") or 0) < HOMEPAGE_SHELL_CACHE_SECONDS
    ):
        return HTMLResponse(cached_html)

    _schedule_homepage_warm(request)
    html = _EMERGENCY_HOME_HTML or _prime_emergency_home_html()
    return HTMLResponse(
        html,
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/api/daily-rotation")
def daily_rotation():
    """Return the latest daily rotation decisions plus live recommendations."""
    soul_map = load_data("data/soul_map.json")
    last_output = soul_map.get("soul_map_state", {}).get("last_selector_output", {})
    recommendations = MindmapBridge().get_brain_recommendations()
    return {
        "status": "success",
        "data": {
            "date": last_output.get("date"),
            "decisions": last_output.get("decisions", []),
            "recommendations": recommendations.get("recommendations", {}),
            "updated_at": soul_map.get("soul_map_state", {}).get("updated_at"),
        },
    }


@app.get("/api/registry")
def get_registry():
    from internal.subnet_names import enrich_subnet_row

    data = load_data("config/registry.json")
    consensus = _consensus_map()
    enriched = {}
    for key, value in data.items():
        item = enrich_subnet_row(dict(value), use_taostats=False)
        subnet_id = item.get("id", int(key))
        item.setdefault("id", subnet_id)
        item.setdefault("netuid", subnet_id)
        decision = consensus.get(subnet_id)
        if decision:
            item["consensus"] = {
                "score": decision.get("consensus_score"),
                "recommended_action": decision.get("recommended_action"),
                "expert_breakdown": decision.get("expert_breakdown"),
            }
        enriched[key] = item
    return enriched


@app.get("/api/subnets")
async def list_subnets(request: Request):
    """List subnets with optional filtering, sorting, and pagination."""
    return await asyncio.to_thread(_list_subnets_sync, request)


def _list_subnets_sync(request: Request):
    from internal.subnet_names import enrich_subnet_row

    # Prefer live on-chain feed (blockmachine) with TMC overlay; fall back to registry.
    source_rows = load_subnets_source()
    feed_meta = _subnet_feed_meta(source_rows)
    items = []
    for s in source_rows:
        item = _tag_subnet_row(s, feed_meta)
        item.setdefault("id", s.get("netuid", 0))
        item.setdefault("netuid", item.get("id"))
        items.append(enrich_subnet_row(item, use_taostats=False))

    params = request.query_params
    status_filter = params.get("status")
    if status_filter:
        statuses = {s.strip().lower() for s in status_filter.split(",")}
        items = [i for i in items if str(i.get("status", "")).lower() in statuses]

    sort_field = params.get("sort", "id")
    order = params.get("order", "asc").lower()
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
        limit = int(params.get("limit", 0))
        offset = int(params.get("offset", 0))
    except ValueError:
        limit = 0
        offset = 0

    total = len(items)
    if offset:
        items = items[offset:]
    if limit > 0:
        items = items[:limit]

    fields_param = params.get("fields")
    if fields_param:
        allowed = {f.strip() for f in fields_param.split(",") if f.strip()}
        if allowed:
            items = [
                {k: v for k, v in row.items() if k in allowed or k in ("id", "netuid")}
                for row in items
            ]

    return {
        "status": "success",
        "meta": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "source": feed_meta.get("source", "registry"),
            "sources": feed_meta.get("sources", ["registry"]),
        },
        "subnets": items,
    }


@app.get("/api/subnet/{subnet_id}")
def get_subnet(subnet_id: int):
    from internal.subnet_names import enrich_subnet_row

    data = load_data("config/registry.json")
    subnet_data = data.get(str(subnet_id))
    if subnet_data is None:
        return JSONResponse(status_code=404, content={"error": "Subnet not found"})
    merged = enrich_subnet_row(dict(subnet_data), use_taostats=False)
    try:
        live_rows = load_subnets_source()
        for row in live_rows:
            if int(row.get("netuid", row.get("id", -1))) == subnet_id:
                merged.update({k: v for k, v in row.items() if v not in (None, "")})
                merged = enrich_subnet_row(merged, use_taostats=False)
                break
    except Exception:
        pass
    return {"subnet_id": subnet_id, "data": merged}


@app.get("/api/summary")
def get_summary():
    """Lightweight aggregated hero-card data for the dashboard."""
    data = load_data("config/registry.json")
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

    # Featured highlights: top emitter, top staked, top APY, most mentioned.
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


@app.get("/api/stats")
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

    return {
        "status": "success",
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


@app.get("/api/soul-map")
def get_soul_map():
    """Expose the persisted Soul-Map state and feedback history."""
    data = load_data("data/soul_map.json")
    return {"status": "success", "data": data}


@app.get("/api/recommendations")
def get_recommendations():
    """Live Brain recommendations derived from the current registry."""
    bridge = MindmapBridge()
    return {"status": "success", "data": bridge.get_brain_recommendations()}


@app.post("/api/mindmap/feedback")
@limit_or_noop(strict_limit(), override_defaults=True)
async def post_feedback(request: Request):
    """Close the mindmap feedback path into learning + soul-map alignment logs."""
    try:
        payload = await request.json()
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        return {"status": "error", "detail": "JSON body required"}

    result: Dict[str, Any] = {"status": "received", "feedback": payload}

    subnet_id = payload.get("subnet_id")
    recommendation = payload.get("recommendation")
    actual_performance = payload.get("actual_performance")
    if subnet_id and recommendation:
        try:
            from datastore.learning_engine import LearningEngine

            engine = LearningEngine()
            result["learning"] = engine.record_feedback(
                int(subnet_id), str(recommendation), actual_performance or {}
            )
        except Exception as exc:
            logger.warning("mindmap→learning feedback failed: %s", exc)
            result["learning_error"] = str(exc)

    daily_output = payload.get("daily_output") or payload.get("selector_output")
    if isinstance(daily_output, dict) and daily_output.get("decisions"):
        try:
            bridge = MindmapBridge()
            brain = bridge.get_brain_recommendations(payload.get("context"))
            result["alignment"] = bridge.log_feedback(daily_output, brain)
        except Exception as exc:
            logger.warning("mindmap alignment log failed: %s", exc)
            result["alignment_error"] = str(exc)

    note = payload.get("note") or payload.get("message")
    if note and not (subnet_id and recommendation):
        try:
            bridge = MindmapBridge()
            bridge.append_learning_trail(
                {
                    "time": datetime.utcnow().isoformat() + "Z",
                    "subnet": payload.get("subnet") or payload.get("name"),
                    "evidence": {"note": note},
                    "signal": "user_feedback",
                    "decision": payload.get("decision"),
                    "prediction": payload.get("prediction"),
                    "judge": payload.get("judge"),
                }
            )
            result["trail"] = "appended"
        except Exception as exc:
            logger.warning("mindmap trail note failed: %s", exc)

    return result


@app.get("/health")
async def health():
    # Must stay async — sync /health queues behind wedged thread-pool workers on Fly.
    return PlainTextResponse("OK")


@app.get("/preview/k3-hold")
async def preview_k3_hold(request: Request):
    """SSR preview for K3 HOLD+candidate — hydrate off for phone sign-off."""
    from internal.preview.k3_hold import build_k3_hold_preview_context

    return templates.TemplateResponse(
        "preview/k3_hold.html",
        build_k3_hold_preview_context(request),
    )


@app.get("/preview/k3-pump-alert")
async def preview_k3_pump_alert(request: Request):
    """SSR preview for K3-8 Pump Alert lane — hydrate off for phone sign-off."""
    from internal.preview.k3_pump_alert import build_k3_pump_alert_preview_context

    return templates.TemplateResponse(
        "preview/k3_pump_alert.html",
        build_k3_pump_alert_preview_context(request),
    )


@app.get("/api/pump-alerts")
async def api_pump_alerts():
    """Pump lane — must not block the event loop (single-worker Fly wedge)."""

    def _build():
        from internal.learning.pump_alert import build_pump_alerts
        from internal.pump.state import load_state
        from internal.subnet_names import enrich_subnet_row

        state = load_state()
        netuids = set()
        for entry in (state.get("subnets") or {}).values():
            if not isinstance(entry, dict):
                continue
            nu = entry.get("netuid")
            if nu is not None:
                try:
                    netuids.add(int(nu))
                except (TypeError, ValueError):
                    continue
        registry = load_data("config/registry.json")
        rows = []
        for nu in sorted(netuids):
            raw = registry.get(str(nu)) if isinstance(registry, dict) else None
            row = dict(raw) if isinstance(raw, dict) else {"netuid": nu}
            row.setdefault("netuid", nu)
            rows.append(enrich_subnet_row(row, use_taostats=False))
        return build_pump_alerts(rows)

    return await asyncio.to_thread(_build)


# ---------------------------------------------------------------------------
# SimiVision picks (ported from server_original.py onto the FastAPI foundation)
#
# NOTE: pick-generation is read-only here except hour-pick recording via
# pick_history + learning loop (/api/pick-history). Scenario memory has its own slice.
# Subnets come from the deduped taomarketcap source so picks never repeat a subnet.
# ---------------------------------------------------------------------------

# taomarketcap-shaped static fallback used when live/cached data is unavailable.
_STATIC_SUBNETS = [
    {"netuid": 29, "name": "Coldint", "emission": 3.0, "apy": 42.5, "volume": 1250000,
     "market_cap": 45000000, "price": 28.50, "price_change_24h": 12.3,
     "price_change_7d": 18.2, "price_change_30d": 24.9, "status": "active"},
    {"netuid": 19, "name": "Inference", "emission": 2.1, "apy": 38.2, "volume": 980000,
     "market_cap": 32000000, "price": 15.20, "price_change_24h": 8.7,
     "price_change_7d": 12.1, "price_change_30d": 16.8, "status": "active"},
    {"netuid": 12, "name": "Compute", "emission": 1.8, "apy": 35.1, "volume": 750000,
     "market_cap": 28000000, "price": 12.40, "price_change_24h": 5.2,
     "price_change_7d": 9.4, "price_change_30d": 13.0, "status": "active"},
]


def _get_subnets_with_source(*, timeout: float | None = None):
    """Return (subnets, source) for picks — tradable only (excludes Root)."""
    from internal.subnets.tradable import tradable_subnets

    try:
        from internal.subnets.feed import get_council_subnet_feed

        subnets, src = get_council_subnet_feed(timeout=timeout)
        tradable = tradable_subnets(subnets)
        if tradable:
            return tradable, src
    except Exception as exc:
        logger.warning("council subnet feed failed: %s", exc)

    return tradable_subnets([dict(s) for s in _STATIC_SUBNETS]), "static-fallback"


def _get_subnets_hydrate():
    """Registry-only rows for client hydrate — never blocks on live feeds."""
    from internal.subnet_names import enrich_subnet_rows
    from internal.subnets.feed import registry_subnet_rows
    from internal.subnets.tradable import tradable_subnets

    rows = enrich_subnet_rows(registry_subnet_rows())
    tradable = tradable_subnets(rows)
    if tradable:
        return tradable, "registry-fallback"
    return tradable_subnets([dict(s) for s in _STATIC_SUBNETS]), "static-fallback"



def _market_mood_proxy(subnets: List[Dict[str, Any]]) -> float:
    """Market-wide 24h change proxy from the average subnet change."""
    changes = []
    for sn in subnets or []:
        try:
            changes.append(float(sn.get("price_change_24h", 0) or 0))
        except (TypeError, ValueError):
            continue
    return sum(changes) / len(changes) if changes else 0.0


def _market_context_with_weights(subnets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Market context for Council scoring — includes learned expert weights."""
    tao_chg = _market_mood_proxy(subnets)
    gainers = 0
    losers = 0
    for sn in subnets or []:
        try:
            chg = float(sn.get("price_change_24h", 0) or 0)
        except (TypeError, ValueError):
            continue
        if chg > 0:
            gainers += 1
        elif chg < 0:
            losers += 1
    market_data = {
        "avg_change_24h": tao_chg,
        "gainers": gainers,
        "losers": losers,
    }
    return {
        "tao_change_24h": tao_chg,
        "weights": effective_weights(market_data),
    }


def _subnet_for_pick(subnets: List[Dict[str, Any]], pick: Dict[str, Any]) -> Dict[str, Any]:
    subnet_info = pick.get("subnet") if isinstance(pick.get("subnet"), dict) else {}
    netuid = pick.get("netuid") or subnet_info.get("netuid")
    if netuid is not None:
        for sn in subnets:
            if sn.get("netuid") == netuid:
                return sn
    if subnet_info:
        return {**subnet_info, "netuid": netuid}
    return {}


def _record_pick_in_learning_loop(
    pick: Dict[str, Any],
    subnets: List[Dict[str, Any]],
    market_context: Dict[str, Any],
    horizon_type: str,
) -> None:
    """Pick → prediction → resolver → weights (closes the learning loop)."""
    if not pick:
        return
    try:
        from internal.learning.prediction_loop import record_pick_prediction

        subnet = _subnet_for_pick(subnets, pick)
        if subnet.get("price"):
            stored = record_pick_prediction(
                pick,
                subnet,
                horizon_type=horizon_type,
                market_context=market_context,
            )
            if stored and horizon_type == "hour":
                try:
                    from internal.council import pick_history

                    pick_history.record_hour_pick(
                        pick,
                        subnet,
                        prediction_id=stored.get("id"),
                    )
                except Exception as exc:
                    logger.warning("pick_history record failed: %s", exc)
    except Exception as exc:
        logger.warning("Learning loop record failed (%s pick): %s", horizon_type, exc)


def _highest_emission_pick(subnets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pick-shaped fallback using the highest-emission subnet."""
    best = max(subnets, key=lambda s: s.get("emission", 0) or 0) if subnets else {}
    return {
        "subnet": {"netuid": best.get("netuid"), "name": best.get("name"), "symbol": best.get("symbol")},
        "score": 0.0,
        "confidence": 0.0,
        "expert_contributions": {},
        "scenario_tags": {"fallback": "highest-emission"},
        "signals": {
            "price_change_24h": best.get("price_change_24h"),
            "price_change_7d": best.get("price_change_7d"),
            "emission": best.get("emission"),
            "apy": best.get("apy"),
            "volume": best.get("volume"),
        },
        "action": "long",
    }


def _safe_simivision_payload(
    subnets: Optional[List[Dict[str, Any]]] = None,
    source: Optional[str] = None,
    daily_pick: Optional[Dict[str, Any]] = None,
    market_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """SimiVision Weighing Room — council shortlist alternatives, shaped for UI."""
    from internal.simivision.weighing_room import (
        build_weighing_candidates_from_shortlist,
        shape_weighing_board,
    )

    if subnets is None:
        subnets, source = _get_subnets_with_source()
    source = source or "unknown"
    if market_context is None:
        market_context = _market_context_with_weights(subnets)

    raw_top, total_considered = build_weighing_candidates_from_shortlist(
        subnets, daily_pick, market_context
    )
    board_source = "council-shortlist" if raw_top else "council-shortlist-empty"
    updated_at = datetime.utcnow().isoformat() + "Z"
    top, weigh_meta = shape_weighing_board(
        raw_top,
        pool_count=total_considered,
        total_considered=total_considered,
        daily_pick=daily_pick,
        updated_at=updated_at,
    )
    caution_cells: List[Dict[str, Any]] = []
    try:
        from internal.simivision.caution_cells import build_caution_cells

        fading = {
            int(r["netuid"])
            for r in top
            if isinstance(r, dict)
            and r.get("deliberation_state") == "FADING"
            and r.get("netuid") is not None
        }
        market_context = None
        try:
            market_context = _market_context_with_weights(subnets)
        except Exception:
            market_context = {}
        caution_cells = build_caution_cells(
            subnets,
            daily_pick=daily_pick,
            market_context=market_context,
            fading_netuids=fading,
        )
    except Exception as exc:
        logger.warning("caution_cells build failed: %s", exc)
    meta = {
        "count": len(subnets),
        "source": board_source,
        "updated_at": updated_at,
        "caution_cells": caution_cells,
        **weigh_meta,
    }
    return {"status": "success", "data": {"top": top, "meta": meta}}


def _build_hour_pick_payload(sn: Dict[str, Any], score: Dict[str, Any]) -> Dict[str, Any]:
    """Format a subnet + hour state-vector into the public hour-pick shape."""
    from internal.council.state_vector import unpack_score_learning_fields

    learning = unpack_score_learning_fields(score)
    try:
        from internal.subnets.impact import impact_profile

        impact = impact_profile(sn)
    except Exception:
        impact = None
    metric_signals = {
        "price_change_24h": sn.get("price_change_24h"),
        "price_change_7d": sn.get("price_change_7d"),
        "emission": sn.get("emission"),
        "apy": sn.get("apy"),
        "volume": sn.get("volume"),
    }
    return {
        "subnet": {"netuid": sn.get("netuid"), "name": sn.get("name"), "symbol": sn.get("symbol")},
        "score": score["total_score"],
        "confidence": score["confidence"],
        "expert_contributions": score["expert_contributions"],
        "scenario_tags": score["scenario_tags"],
        "signals": learning["signal_impact"] or metric_signals,
        "signal_impact": learning["signal_impact"],
        "signal_contributions": learning["signal_contributions"],
        "active_signals": learning["active_signals"],
        "action": "long",
        "impact": impact,
    }


def _ordered_hour_picks(subnets, market_context, limit: int = 3) -> List[Dict[str, Any]]:
    """Canonical ordered hourly picks: RedTeam-audited #1 (select_hourly_pick),
    then distinct fill by raw hour score. Excludes the #1 netuid so no subnet
    repeats. #1 is recorded into the learning loop (pick → prediction)."""
    picks: List[Dict[str, Any]] = []
    if not subnets:
        return picks

    audited = None
    if _PICKS_ENGINE:
        try:
            audited = select_hourly_pick(subnets, market_context)
        except Exception as exc:
            logger.warning("select_hourly_pick failed: %s", exc)
    if not audited:
        audited = _highest_emission_pick(subnets)

    top_netuid = None
    if isinstance(audited, dict) and isinstance(audited.get("subnet"), dict):
        top_netuid = audited["subnet"].get("netuid")
        if "signals" not in audited:
            # Prefer scored signal_impact; fall back to market snapshot metrics.
            if isinstance(audited.get("signal_impact"), dict):
                audited["signals"] = audited["signal_impact"]
            else:
                src = next((s for s in subnets if s.get("netuid") == top_netuid), {})
                audited["signals"] = {
                    "price_change_24h": src.get("price_change_24h"),
                    "price_change_7d": src.get("price_change_7d"),
                    "emission": src.get("emission"),
                    "apy": src.get("apy"),
                    "volume": src.get("volume"),
                }
        if not audited.get("impact"):
            try:
                from internal.subnets.impact import impact_profile

                src = next((s for s in subnets if s.get("netuid") == top_netuid), {})
                if src:
                    audited["impact"] = impact_profile(src)
            except Exception:
                pass

    def _unify(payload, sn):
        subnet = payload.get("subnet") if isinstance(payload.get("subnet"), dict) else {}
        unified = dict(payload)
        unified.setdefault("netuid", subnet.get("netuid", sn.get("netuid")))
        unified.setdefault("name", subnet.get("name", sn.get("name")))
        unified.setdefault("symbol", subnet.get("symbol", sn.get("symbol")))
        unified.setdefault("score", payload.get("score", 0.0))
        unified.setdefault("confidence", payload.get("confidence", 0.0))
        unified.setdefault("scenario_tags", payload.get("scenario_tags", {}))
        unified.setdefault("signals", payload.get("signals", {}))
        return unified

    src = next((s for s in subnets if s.get("netuid") == top_netuid), {})
    picks.append(_unify(audited, src))
    # Close the learning loop for the audited #1 hour pick.
    _record_pick_in_learning_loop(audited, subnets, market_context, "hour")

    if _PICKS_ENGINE:
        from internal.council.score_cache import score_universe

        hour_scored, _ = score_universe(
            subnets,
            market_context,
            score_hour=score_subnet_for_hour,
            score_day=score_subnet_for_day,
        )
        scored = [
            item for item in hour_scored
            if top_netuid is None or item["subnet"].get("netuid") != top_netuid
        ]
        scored.sort(key=lambda x: x["score"]["total_score"], reverse=True)
        for item in scored[: max(0, limit - len(picks))]:
            picks.append(_unify(_build_hour_pick_payload(item["subnet"], item["score"]), item["subnet"]))

    return picks[:limit]


@app.get("/api/simivision")
def api_simivision():
    """SimiVision Weighing Room — deliberation board (Daily Call excluded)."""
    hydrate_timeout = float(os.environ.get("HYDRATE_SUBNETS_TIMEOUT_SECONDS", "4"))
    subnets, source = _get_subnets_with_source(timeout=hydrate_timeout)
    if not subnets:
        subnets, source = _get_subnets_hydrate()
    subnets = _cap_subnets_for_scoring(subnets)
    daily_pick: Optional[Dict[str, Any]] = None
    market_context: Optional[Dict[str, Any]] = None
    try:
        if _PICKS_ENGINE:
            market_context = _market_context_with_weights(subnets)
            from internal.council.daily_pick_engine import _find_today, _load

            existing = _find_today(_load())
            daily_pick = existing if existing is not None else None
    except Exception as exc:
        logger.warning("simivision daily-pick context skipped: %s", exc)
    return _safe_simivision_payload(
        subnets=subnets,
        source=source,
        daily_pick=daily_pick,
        market_context=market_context,
    )


@app.get("/api/top-picks")
def api_top_picks():
    """Top 3 subnets by short-horizon (hour) and 24h (day) Council scores."""
    from internal.council.score_cache import score_universe

    hydrate_timeout = float(os.environ.get("HYDRATE_SUBNETS_TIMEOUT_SECONDS", "4"))
    subnets, _ = _get_subnets_with_source(timeout=hydrate_timeout)
    if not subnets:
        subnets, _ = _get_subnets_hydrate()
    subnets = _cap_subnets_for_scoring(subnets)
    if not _PICKS_ENGINE:
        return {"hour_picks": [], "day_picks": [], "error": "pick engine unavailable"}
    market_context = _market_context_with_weights(subnets)
    hour_scored, day_scored = score_universe(
        subnets,
        market_context,
        score_hour=score_subnet_for_hour,
        score_day=score_subnet_for_day,
    )
    hour_scored.sort(key=lambda x: x["score"]["total_score"], reverse=True)
    day_scored.sort(key=lambda x: x["score"]["total_score"], reverse=True)

    def _format(item):
        sn, sc = item["subnet"], item["score"]
        return {
            "netuid": sn.get("netuid"),
            "name": sn.get("name"),
            "symbol": sn.get("symbol"),
            "score": sc["total_score"],
            "confidence": sc["confidence"],
            "expert_contributions": sc["expert_contributions"],
            "signals": {
                "price_change_24h": sn.get("price_change_24h"),
                "price_change_7d": sn.get("price_change_7d"),
                "emission": sn.get("emission"),
                "apy": sn.get("apy"),
                "volume": sn.get("volume"),
            },
            "scenario_tags": sc["scenario_tags"],
        }

    return {
        "hour_picks": [_format(i) for i in hour_scored[:3]],
        "day_picks": [_format(i) for i in day_scored[:3]],
    }


def _pick_netuid_from_daily_payload(payload: Any) -> Optional[int]:
    if not isinstance(payload, dict):
        return None
    for key in ("pick", "candidate"):
        block = payload.get(key)
        if isinstance(block, dict):
            subnet = block.get("subnet") if isinstance(block.get("subnet"), dict) else block
            netuid = subnet.get("netuid") if isinstance(subnet, dict) else block.get("netuid")
            if netuid is not None:
                return int(netuid)
        pred = block.get("prediction") if isinstance(block, dict) else None
        if isinstance(pred, dict) and pred.get("netuid") is not None:
            return int(pred["netuid"])
    return None


def _daily_pick_weighed_shortlist(pick_payload: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Council deliberation rows for hero weighed-against — uses live subnet prices."""
    if not isinstance(pick_payload, dict):
        return []
    from internal.learning.dpick_shortlist import attach_shortlist_to_daily_pick

    hydrate_timeout = float(os.environ.get("HYDRATE_SUBNETS_TIMEOUT_SECONDS", "4"))
    subnets, _ = _get_subnets_with_source(timeout=hydrate_timeout)
    if not subnets:
        subnets, _ = _get_subnets_hydrate()
    subnets = _cap_subnets_for_scoring(subnets)
    if not subnets:
        return []
    market_context = _market_context_with_weights(subnets)
    enriched = attach_shortlist_to_daily_pick(dict(pick_payload), subnets, market_context)
    shortlist = enriched.get("shortlist")
    return shortlist if isinstance(shortlist, list) else []


@app.get("/api/daily-pick/weighed")
def api_daily_pick_weighed():
    """Deferred hydrate read — shortlist only, scored on live-priced subnets."""
    from internal.council.daily_pick_engine import _find_today, _load

    existing = _find_today(_load())
    if existing is None:
        return {"shortlist": []}
    return {"shortlist": _daily_pick_weighed_shortlist(existing)}


@app.get("/api/daily-pick")
def api_daily_pick(full: bool = False):
    """Today's audited daily pick from the Council engine."""
    from internal.council.daily_pick_engine import _find_today, _load
    from internal.whales.enrichment_badge import empty_whale_flow_badge, whale_flow_badge

    existing = _find_today(_load())
    if existing is not None:
        result = dict(existing)
        if full:
            try:
                subnets, _ = _get_subnets_hydrate()
                market_context = _market_context_with_weights(subnets)
                result = _enrich_daily_pick_payload(result, subnets, market_context)
            except Exception as exc:
                logger.warning("daily-pick full enrich skipped: %s", exc)
                result = _enrich_daily_pick_payload_lite(result)
            netuid = _pick_netuid_from_daily_payload(result)
            result["enrichment_badge"] = (
                whale_flow_badge(netuid) if netuid is not None else empty_whale_flow_badge()
            )
        else:
            result = _enrich_daily_pick_payload_lite(result)
            result["enrichment_badge"] = empty_whale_flow_badge("lite_read")
        return result

    subnets, _ = _get_subnets_hydrate()
    if not _PICKS_ENGINE:
        return {
            "status": "error",
            "date": datetime.utcnow().date().isoformat(),
            "action": "HOLD",
            "reason": "pick engine unavailable",
            "pick": None,
        }
    market_context = _market_context_with_weights(subnets)
    try:
        result = get_or_create_today_pick(subnets, market_context)
        if isinstance(result, dict):
            netuid = _pick_netuid_from_daily_payload(result)
            result = _enrich_daily_pick_payload(result, subnets, market_context)
            result = {
                **result,
                "enrichment_badge": (
                    whale_flow_badge(netuid) if netuid is not None else empty_whale_flow_badge()
                ),
            }
        return result
    except Exception as e:
        logger.error("Error fetching daily pick: %s", e)
        return {
            "status": "error",
            "date": datetime.utcnow().date().isoformat(),
            "action": "HOLD",
            "reason": str(e),
            "pick": None,
        }


@app.get("/api/pick-explain/{netuid}")
def api_pick_explain(netuid: int):
    """§32 — why this subnet was or was not today's council pick."""
    subnets, _ = _get_subnets_with_source()
    market_context = _market_context_with_weights(subnets)
    try:
        from internal.council.pick_explain import explain_subnet

        return explain_subnet(netuid, subnets, market_context)
    except Exception as exc:
        logger.error("pick-explain failed for SN%d: %s", netuid, exc)
        return {"status": "error", "netuid": netuid, "error": str(exc)}


@app.get("/api/top-pick/day")
def api_top_pick_day():
    """Top pick for the current day, with a safe highest-emission fallback."""
    subnets, _ = _get_subnets_with_source()
    day_pick = None
    if _PICKS_ENGINE:
        market_context = _market_context_with_weights(subnets)
        try:
            raw = get_or_create_today_pick(subnets, market_context)
            day_pick = raw.get("pick") if isinstance(raw, dict) and raw.get("pick") else raw
        except Exception as exc:
            logger.error("Error selecting daily pick: %s", exc)
    if not day_pick:
        return {"picks": [_highest_emission_pick(subnets)]}
    return {"picks": [day_pick]}


@app.get("/api/top-pick/hour")
def api_top_pick_hour():
    """Top short-horizon picks (audited #1 + distinct fill), with fallback.

    Response shape is always ``{"picks": [<pick>, ...]}`` — never a bare list.
    """
    subnets, _ = _get_subnets_with_source()
    market_context = _market_context_with_weights(subnets)
    picks: List[Dict[str, Any]] = []
    try:
        picks = _ordered_hour_picks(subnets, market_context, limit=3)
    except Exception as e:
        logger.error("Error fetching hour pick: %s", e)
    if not picks:
        picks = [_highest_emission_pick(subnets)]
    return {"picks": picks}


from internal.instant_bailout import wrap_instant_bailout

app = wrap_instant_bailout(
    app,
    get_homepage_html=_bailout_homepage_html,
    schedule_warm=lambda: _schedule_homepage_warm(None),
)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 50745))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
