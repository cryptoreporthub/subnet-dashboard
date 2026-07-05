"""All API and web routes."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from server.config import *  # noqa: F403

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/health")
def health_check():
    return PlainTextResponse("OK")


@router.get("/api/health")
def api_health_check():
    """JSON health probe for Fly.io / monitoring tooling.

    Mirrors the plain-text ``/health`` route but returns a JSON body so probes
    that expect a structured response (and the ``/api/health`` path requested
    by external monitors) get a 200 instead of a 404.
    """
    return {"status": "ok"}


@router.get("/api/freshness")
def api_freshness():
    """Per-section "last updated" timestamps for the dashboard freshness badges.

    Returns ``{"last_updated": {section: iso_ts, ...}, "now": <iso>}``. The
    frontend polls this on load and every 30s to render "updated Xm ago"
    badges next to each section heading.
    """
    return _freshness_snapshot()


@router.get("/api/pick-history")
def api_pick_history():
    """Pick-of-the-Hour history + aggregate success metric.

    Returns the currently-tenured pick, the most recent finalized picks (each
    with absolute/median/percentile returns + success flag), and aggregate
    success stats (wins/losses/success_rate). A pick is "successful" when its
    absolute return beats the median subnet return over its tenure.
    """
    return _hour_pick_history(limit=20)


@router.get("/api/price-tracking/baselines")
def api_price_tracking_baselines():
    """Return the recorded baseline price history for all tracked subnets."""
    try:
        baseline_file = os.environ.get(
            "PRICE_BASELINE_FILE", "data/price_baselines.json"
        )
        if not os.path.exists(baseline_file):
            return {
                "status": "success",
                "meta": {"count": 0, "source": "file"},
                "baselines": [],
            }
        with open(baseline_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            data = []
        netuids = {e.get("netuid") for e in data if e.get("netuid") is not None}
        return {
            "status": "success",
            "meta": {
                "count": len(data),
                "tracked_subnets": len(netuids),
                "source": "file",
            },
            "baselines": data,
        }
    except Exception as exc:
        logger.warning("price-tracking/baselines failed: %s", exc)
        return {"status": "error", "error": str(exc), "baselines": []}


@router.get("/api/price-tracking/outcomes")
def api_price_tracking_outcomes():
    """Return recorded price outcomes (for debugging/verification)."""
    try:
        if not _MESSAGE_INTEL_AVAILABLE:
            return {"status": "success", "meta": {"count": 0}, "outcomes": []}
        db = _get_message_intel_db()
        if db is None:
            return {"status": "success", "meta": {"count": 0}, "outcomes": []}
        outcomes = db.list_price_outcomes(limit=100)
        return {
            "status": "success",
            "meta": {"count": len(outcomes)},
            "outcomes": outcomes,
        }
    except Exception as exc:
        logger.warning("price-tracking/outcomes failed: %s", exc)
        return {"status": "error", "error": str(exc), "outcomes": []}


@router.get("/api/resolve-predictions")
def api_resolve_predictions():
    """Trigger prediction resolution for any due predictions."""
    try:
        subnets, _ = _get_subnets_with_source()
        result = resolver.resolve_due_predictions(subnets)
        return {"status": "success", "data": result}
    except Exception as exc:
        logger.warning("resolve_due_predictions failed: %s", exc)
        return {
            "status": "stub",
            "data": {"resolved_now": [], "resolved": [], "pending": [], "stats": {}},
            "error": str(exc),
        }


@router.get("/api/council/weights")
def api_council_weights():
    """Return the current Council expert weights."""
    try:
        return {"status": "success", "data": load_weights()}
    except Exception as exc:
        logger.warning("load_weights failed: %s", exc)
        return {
            "status": "stub",
            "data": {"quant": 1.0, "hype": 1.0, "contrarian": 1.0, "technical": 1.0},
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Judge Council API endpoints
# ---------------------------------------------------------------------------
import threading

# In-memory cache for judge scores
_JUDGE_SCORES: List[Dict[str, Any]] = []
_JUDGE_SCORES_LOCK = threading.Lock()
_JUDGE_SCORES_REFRESHED = ""


def _refresh_judge_scores():
    """Refresh judge scores in background."""
    global _JUDGE_SCORES, _JUDGE_SCORES_REFRESHED
    try:
        subnets_data = get_all_subnets()
        subnets = subnets_data if isinstance(subnets_data, list) else subnets_data.get("subnets", [])
        scores = score_all_subnets(subnets)
        with _JUDGE_SCORES_LOCK:
            _JUDGE_SCORES = scores
            _JUDGE_SCORES_REFRESHED = datetime.utcnow().isoformat() + "Z"
    except Exception:
        pass
    # Schedule next refresh in 5 minutes
    timer = threading.Timer(300, _refresh_judge_scores)
    timer.daemon = True
    timer.start()


@router.get("/api/judges")
async def api_judges():
    """Return all subnet judge scores sorted by consensus."""
    with _JUDGE_SCORES_LOCK:
        scores = list(_JUDGE_SCORES)
    return {
        "judges": scores,
        "meta": {
            "count": len(scores),
            "refreshed_at": _JUDGE_SCORES_REFRESHED,
            "degraded_sources": [],
        },
    }


@router.get("/api/judges/{netuid}")
async def api_judges_netuid(netuid: int):
    """Return detailed judge breakdown for one subnet."""
    with _JUDGE_SCORES_LOCK:
        for entry in _JUDGE_SCORES:
            if entry["netuid"] == netuid:
                return entry
    # If not cached, compute live
    try:
        subnets_data = get_all_subnets()
        subnets = subnets_data if isinstance(subnets_data, list) else subnets_data.get("subnets", [])
        target = next((s for s in subnets if s.get("netuid") == netuid or s.get("id") == netuid), None)
        if target:
            return score_subnet(netuid, target)
    except Exception:
        pass
    return {"error": "subnet not found", "netuid": netuid}


@router.get("/api/paper-portfolio")
async def api_paper_portfolio():
    """Return aggregate paper portfolios for all judges."""
    try:
        portfolios = all_portfolios()
    except Exception:
        portfolios = {}
    return {"aggregate": _aggregate_portfolios(portfolios), "judges": portfolios}


def _aggregate_portfolios(portfolios):
    """Aggregate all judge portfolios into a single summary."""
    total_open = 0
    total_closed = 0
    total_pl = 0.0
    total_wins = 0
    total_losses = 0
    for name, pf in portfolios.items():
        if not isinstance(pf, dict):
            continue
        open_pos = pf.get("open_positions", pf.get("open", []))
        closed_pos = pf.get("closed_positions", pf.get("closed", []))
        total_open += len(open_pos) if isinstance(open_pos, list) else 0
        total_closed += len(closed_pos) if isinstance(closed_pos, list) else 0
        pl = pf.get("pnl", pf.get("realized_pnl", pf.get("pl", 0)))
        total_pl += pl if isinstance(pl, (int, float)) else 0
        wins = pf.get("wins", pf.get("win_count", 0))
        losses = pf.get("losses", pf.get("loss_count", 0))
        total_wins += wins if isinstance(wins, int) else 0
        total_losses += losses if isinstance(losses, int) else 0
    total_trades = total_wins + total_losses
    return {
        "open_positions": total_open,
        "closed_positions": total_closed,
        "total_pnl": round(total_pl, 4),
        "win_rate": round(total_wins / total_trades, 4) if total_trades > 0 else 0,
        "total_trades": total_trades,
    }


@router.get("/api/postmortems")
async def api_postmortems(judge: Optional[str] = None):
    """Return all postmortems, optionally filtered by judge name."""
    try:
        if judge:
            pms = list_for_judge(judge)
            return {"judge": judge, "postmortems": pms if isinstance(pms, list) else []}
        pms = all_postmortems()
        return {"postmortems": pms if isinstance(pms, dict) else {}}
    except Exception:
        return {"postmortems": {}}


@router.get("/api/postmortems/{judge_name}")
async def api_postmortems_by_judge(judge_name: str):
    """Return postmortems for a specific judge (alternative path)."""
    try:
        pms = list_for_judge(judge_name)
        return {"judge": judge_name, "postmortems": pms if isinstance(pms, list) else []}
    except Exception:
        return {"judge": judge_name, "postmortems": []}


@router.get("/api/portfolios")
def api_portfolios():
    """Return the current paper portfolios for Oracle, Echo and Pulse."""
    try:
        return {"status": "success", "portfolios": all_portfolios()}
    except Exception as exc:
        logger.warning("api_portfolios failed: %s", exc)
        return {"status": "stub", "portfolios": {}, "error": str(exc)}


@router.get("/api/judges/{judge}/postmortems")
def api_judge_postmortems(judge: str):
    """Return scientific-method postmortems for a single judge."""
    try:
        name = judge.lower()
        if get_judge(name) is None:
            return {"status": "error", "error": f"Unknown judge: {judge}"}
        return {"status": "success", "judge": name, "postmortems": list_for_judge(name)}
    except Exception as exc:
        logger.warning("api_judge_postmortems failed: %s", exc)
        return {"status": "stub", "judge": judge, "postmortems": [], "error": str(exc)}


@router.get("/api/oracle")
def api_oracle():
    """Return a minimal oracle snapshot from live subnet data."""
    try:
        subnets, source = _get_subnets_with_source()
        snapshot = [
            {
                "netuid": s.get("netuid"),
                "name": s.get("name"),
                "symbol": s.get("symbol"),
                "price": s.get("price"),
                "price_change_24h": s.get("price_change_24h"),
            }
            for s in subnets[:10]
        ]
        return {"status": "success", "source": source, "data": snapshot}
    except Exception as exc:
        logger.warning("oracle snapshot failed: %s", exc)
        return {"status": "stub", "source": "error", "data": [], "error": str(exc)}


def _highest_emission_pick(subnets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a pick-shaped fallback using the highest-emission subnet."""
    best = max(subnets, key=lambda s: s.get("emission", 0) or 0) if subnets else {}
    return {
        "subnet": {
            "netuid": best.get("netuid"),
            "name": best.get("name"),
            "symbol": best.get("symbol"),
        },
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


def _fallback_state_pick(subnets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a flat pick-shaped fallback for the Live Council State Vector.

    Mirrors the shape used by the dashboard's hour/day pick cards (flat
    ``netuid``/``name``/``score``/``confidence``/``signals`` keys) so the
    homepage never renders an empty council state vector. Falls back to the
    highest-ranked subnet (by emission, then APY, then volume).
    """
    if not subnets:
        return {}
    best = max(
        subnets,
        key=lambda s: (s.get("emission", 0) or 0, s.get("apy", 0) or 0, s.get("volume", 0) or 0),
    )
    return {
        "netuid": best.get("netuid"),
        "name": best.get("name"),
        "symbol": best.get("symbol"),
        "score": 0.0,
        "confidence": 0.0,
        "expert_contributions": {},
        "scenario_tags": {"fallback": "highest-ranked"},
        "signals": {
            "price_change_24h": best.get("price_change_24h"),
            "price_change_7d": best.get("price_change_7d"),
            "emission": best.get("emission"),
            "apy": best.get("apy"),
            "volume": best.get("volume"),
        },
        "action": "long",
        "rationale": "Council convening — picks refresh every 60 minutes.",
        "fallback": True,
    }


@router.get("/api/top-pick/day")
def api_top_pick_day():
    """Return the top pick for the current day with a safe fallback."""
    subnets, _ = _get_subnets_with_source()
    # Use the same real market-wide mood proxy as the homepage so the day
    # pick endpoint stays in sync with the rendered dashboard.
    market_context = {"tao_change_24h": _market_mood_proxy(subnets)}
    try:
        _dp_raw = get_or_create_today_pick(subnets, market_context)
        day_pick = _dp_raw.get("pick") if isinstance(_dp_raw, dict) and _dp_raw.get("pick") else _dp_raw
    except Exception as exc:
        logger.error("Error selecting daily pick: %s", exc)
        day_pick = None
    if not day_pick:
        return {"picks": [_highest_emission_pick(subnets)]}
    _mark_fresh("top_pick_day")
    # Record the day pick's market context into the scenario memory so
    # /api/scenario-memory reflects real picks, not just resolved predictions.
    try:
        candidate = day_pick.get("subnet") if isinstance(day_pick, dict) else None
        if isinstance(candidate, dict):
            sn = next((s for s in subnets if s.get("netuid") == candidate.get("netuid")), {})
            _record_pick_scenario({
                "name": candidate.get("name"),
                "netuid": candidate.get("netuid"),
                "score": day_pick.get("score", 0.0),
                "confidence": day_pick.get("confidence", 0.0),
                "scenario_tags": day_pick.get("scenario_tags", {}),
                "signals": {
                    "price_change_24h": sn.get("price_change_24h"),
                    "price_change_7d": sn.get("price_change_7d"),
                    "emission": sn.get("emission"),
                    "apy": sn.get("apy"),
                    "volume": sn.get("volume"),
                },
            }, market_context)
    except Exception as exc:
        logger.warning("day pick scenario record failed: %s", exc)
    return {"picks": [day_pick]}


@router.get("/api/subnets")
def api_subnets_safe():
    subnets, source = _get_subnets_with_source()
    return {
        "status": "success",
        "meta": {
            "count": len(subnets),
            "source": source,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        },
        "subnets": subnets,
    }


@router.get("/api/simivision")
def api_simivision_safe():
    return _safe_simivision_payload()


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


@router.get("/api/mindmap/summary")
def api_mindmap_summary_safe():
    simivision = _safe_simivision_payload()["data"]
    # Pull live Council expert weights and resolver stats so the mindmap stays
    # wired into the evidence -> signal -> decision -> learning cycle.
    engine = LearningEngine()
    stats = engine.get_stats()
    expert_weights = stats.get("expert_weights", {})
    resolved = resolver.get_resolved_predictions()
    scenario_summary = _safe_scenario_memory_summary()
    rotation_summary = _safe_rotation_summary()
    return {
        "status": "success",
        "data": {
            "acknowledgment": "Dashboard data ready",
            "noticed": ["Using safe cached subnet snapshot"],
            "opinion_changes": ["No significant opinion changes"],
            "technical_indicators": ["No strong technical signals"],
            "conviction": {
                "current": 50.0,
                "trend": "stable",
                "explanation": f"Derived from {simivision['meta']['count']} subnets",
            },
            "expert_insights": [
                {"expert": name.title(), "weight": weight}
                for name, weight in expert_weights.items()
            ],
            "expert_weights": expert_weights,
            "resolved_predictions": {
                "total": resolved.get("stats", {}).get("total", 0),
                "correct": resolved.get("stats", {}).get("correct", 0),
                "wrong": resolved.get("stats", {}).get("wrong", 0),
                "pending": resolved.get("stats", {}).get("pending", 0),
                "accuracy": resolved.get("stats", {}).get("accuracy", 0.0),
            },
            "scenario_memory": scenario_summary,
            "rotation_tracker": rotation_summary,
            "learning_status": {
                "enabled": True,
                "records": stats.get("total_records", 0),
                "last_updated": stats.get("last_updated") or simivision["meta"]["updated_at"],
            },
        },
    }


@router.get("/api/learning/stats")
def api_learning_stats_safe():
    # Use the live learning engine so the dashboard exposes expert weights,
    # resolver stats, accuracy and a valid timestamp.
    engine = LearningEngine()
    stats = engine.get_stats()
    return {
        "status": "success",
        "data": {
            "expert_weights": stats.get("expert_weights", {}),
            "total_records": stats.get("total_records", 0),
            "accuracy": stats.get("accuracy", 0.0),
            "pending": stats.get("pending", 0),
            "resolved": stats.get("resolved", 0),
            "last_updated": stats.get("last_updated") or datetime.utcnow().isoformat() + "Z",
        },
    }


@router.post("/api/learning/trigger")
def api_learning_trigger():
    """Manually trigger a prediction-resolution cycle (the learning loop's judge).

    Runs the resolver immediately so pending predictions are graded and expert
    weights are nudged without waiting for the next scheduled tick (the
    scheduler runs every 15 minutes by default). Returns the cycle summary and
    the current scheduler state. Safe to call repeatedly.
    """
    scheduler = get_prediction_resolver_scheduler()
    if scheduler is None:
        # Scheduler not yet started (e.g. headless test): start it and run a
        # single synchronous cycle so the trigger is still effective.
        start_prediction_resolver_scheduler(immediate=False)
        scheduler = get_prediction_resolver_scheduler()

    cycle: Dict[str, Any] = {}
    if scheduler is not None:
        try:
            cycle = scheduler.run_once()
        except Exception as exc:
            cycle = {"ok": False, "error": str(exc)}

    return {
        "status": "success",
        "data": {
            "cycle": cycle,
            "scheduler": get_prediction_resolver_scheduler_state(),
            "triggered_at": datetime.utcnow().isoformat() + "Z",
        },
    }


@router.get("/api/pump-analytics")
async def api_pump_analytics(netuid: Optional[int] = None):
    """Return pump cycle analytics for all subnets or a specific one.

    Optional ``?netuid=`` filter restricts the response to a single subnet.
    """
    if not _PUMP_TRACKER_AVAILABLE:
        return {
            "status": "error",
            "data": {
                "subnets": [],
                "meta": {
                    "tracked_subnets": 0,
                    "total_cycles": 0,
                    "avg_proneness": 0.0,
                    "top_pump_candidates": [],
                    "updated_at": None,
                },
            },
        }
    tracker = get_pump_tracker()
    if tracker is None:
        return {
            "status": "error",
            "data": {
                "subnets": [],
                "meta": {
                    "tracked_subnets": 0,
                    "total_cycles": 0,
                    "avg_proneness": 0.0,
                    "top_pump_candidates": [],
                    "updated_at": None,
                },
            },
        }
    data = tracker.get_all_analytics()
    if netuid is not None:
        data["data"]["subnets"] = [s for s in data["data"]["subnets"] if s.get("netuid") == netuid]
        data["data"]["meta"]["tracked_subnets"] = len(data["data"]["subnets"])
    return data


# ---------------------------------------------------------------------------
# Message Intelligence API (Telegram → NLP → Jury → Price → Learning)
# ---------------------------------------------------------------------------
@router.post("/api/message-intel/ingest")
async def api_message_intel_ingest(request: Request):
    """Ingest a Telegram message, run NLP + jury, and persist the verdict."""
    if not _MESSAGE_INTEL_AVAILABLE:
        return {"status": "error", "error": "Message intelligence package unavailable"}

    try:
        payload = await request.json()
    except Exception as e:
        return {"status": "error", "error": f"Invalid JSON body: {e}"}

    if not isinstance(payload, dict) or not payload.get("content"):
        return {"status": "error", "error": "Missing required field: content"}

    try:
        db = _get_message_intel_db()
        nlp = _get_message_intel_nlp()
        jury = _get_message_intel_jury()
        price_tracker = _get_message_intel_price_tracker()

        message_id = db.save_message(payload)
        analysis = nlp.analyze(payload.get("content", ""))
        db.save_analysis(message_id, analysis)
        verdict = jury.evaluate(message_id, payload.get("content", ""), analysis)
        db.save_verdict(message_id, verdict)
        price_tracker.snapshot(message_id)

        return {
            "status": "success",
            "message_id": message_id,
            "analysis": analysis,
            "verdict": verdict,
        }
    except Exception as e:
        logger.error("Error ingesting message intel: %s", e)
        return {"status": "error", "error": str(e)}


@router.get("/api/message-intel/list")
async def api_message_intel_list(limit: int = 50, offset: int = 0):
    """List ingested messages with verdicts and analysis."""
    if not _MESSAGE_INTEL_AVAILABLE:
        return {"status": "error", "messages": [], "error": "Message intelligence package unavailable"}

    try:
        db = _get_message_intel_db()
        messages = db.list_messages(limit=limit, offset=offset)
        return {
            "status": "success",
            "count": len(messages),
            "messages": messages,
        }
    except Exception as e:
        logger.error("Error listing message intel: %s", e)
        return {"status": "error", "messages": [], "error": str(e)}


@router.get("/api/message-intel/detail/{msg_id}")
async def api_message_intel_detail(msg_id: int):
    """Return full details for a single message including metrics and verdict."""
    if not _MESSAGE_INTEL_AVAILABLE:
        return {"status": "error", "error": "Message intelligence package unavailable"}

    try:
        db = _get_message_intel_db()
        message = db.get_message(msg_id)
        if message is None:
            return {"status": "error", "error": "Message not found"}
        return {"status": "success", "message": message}
    except Exception as e:
        logger.error("Error fetching message intel detail: %s", e)
        return {"status": "error", "error": str(e)}


@router.get("/api/message-intel/chatter")
async def api_message_intel_chatter(min_conviction: float = 0.6, limit: int = 50):
    """Return high-conviction messages (the 'chatter' feed)."""
    if not _MESSAGE_INTEL_AVAILABLE:
        return {"status": "error", "messages": [], "error": "Message intelligence package unavailable"}

    try:
        db = _get_message_intel_db()
        messages = db.list_high_conviction_messages(min_conviction=min_conviction)
        return {
            "status": "success",
            "count": len(messages[:limit]),
            "messages": messages[:limit],
        }
    except Exception as e:
        logger.error("Error fetching message intel chatter: %s", e)
        return {"status": "error", "messages": [], "error": str(e)}


@router.get("/api/message-intel/patterns")
async def api_message_intel_patterns(limit: int = 20):
    """Return discovered pattern correlations from the learning loop."""
    if not _MESSAGE_INTEL_AVAILABLE:
        return {"status": "error", "patterns": [], "error": "Message intelligence package unavailable"}

    try:
        db = _get_message_intel_db()
        patterns = db.list_patterns(limit=limit)
        return {
            "status": "success",
            "count": len(patterns),
            "patterns": patterns,
        }
    except Exception as e:
        logger.error("Error fetching message intel patterns: %s", e)
        return {"status": "error", "patterns": [], "error": str(e)}


@router.get("/api/indicators/scheduler")
def api_indicators_scheduler():
    """Return the current state of the background indicator scheduler."""
    return {
        "status": "success",
        "data": get_indicator_scheduler_state(),
    }


@router.get("/api/predictions/resolver")
def api_predictions_resolver_state():
    """Return the current state of the background prediction resolver.

    Exposes whether the resolver is running, when it last graded predictions,
    and how many it has resolved/expired so the learning loop's health is
    observable from the dashboard.
    """
    return {
        "status": "success",
        "data": get_prediction_resolver_scheduler_state(),
    }


@router.post("/api/predictions/resolver/run")
def api_predictions_resolver_run():
    """Trigger a single prediction-resolution cycle on demand.

    Useful for clearing a backlog of stuck ``pending`` predictions without
    waiting for the next scheduled tick. Returns the cycle summary.
    """
    scheduler = get_prediction_resolver_scheduler()
    if scheduler is None:
        return {
            "status": "error",
            "message": "prediction resolver scheduler is not initialized",
        }, 500
    try:
        result = scheduler.run_once()
        return {"status": "success", "data": result}
    except Exception as exc:
        logger.warning("Manual prediction resolver run failed: %s", exc)
        return {"status": "error", "message": str(exc)}, 500


@router.post("/api/simivision/chat")
async def api_simivision_chat(request: Request):
    """LLM chat endpoint for SimiVision powered by Chutes AI.

    Accepts a JSON body with a ``message`` field, builds a live-subnet prompt
    from SimiVision context, and calls the Chutes API (``deepseek-ai/DeepSeek-V3.2-TEE``).
    Falls back gracefully when Chutes is unreachable.

    Returns ``{"reply": "...", "model": "chutes/deepseek-v3.2-tee"}`` on success
    or an error shape on failure.
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    message = (payload or {}).get("message", "") or ""

    if not message.strip():
        return {"reply": "Please provide a question in the `message` field.", "model": ""}

    try:
        # 1. Fetch subnet data
        subnets, source = _get_subnets_with_source()
        simivision = _safe_simivision_payload()["data"]

        # 2. Load soul_map.json for learning context
        engine = LearningEngine()
        soul_map = engine.load_soul_map()
        stats = engine.get_stats()
        expert_weights = stats.get("expert_weights", {})

        # 3. Load predictions and daily picks for enriched context
        predictions = _safe_load_json("data", "predictions.json", default={}).get("predictions", [])
        daily_pick_data = _safe_load_json("data", "daily_picks.json", default=[{}])
        daily_pick = daily_pick_data[0] if daily_pick_data else {}

        # 4. Build prompt with context
        top = simivision.get("top", [])
        context = {
            "source": source,
            "simivision_picks": top,
            "market_overview": {
                "count": simivision.get("meta", {}).get("count", len(subnets)),
                "updated_at": simivision.get("meta", {}).get("updated_at"),
            },
            "expert_weights": expert_weights,
            "soul_map": soul_map,
            "predictions": predictions,
            "daily_pick": daily_pick,
        }
        prompt = _build_simivision_prompt(message, context)

        # 5. Call LLM API (with graceful local fallback)
        reply, llm_used = _call_llm(prompt, message, context)

        model_tag = os.environ.get("CHUTES_MODEL", "deepseek-ai/DeepSeek-V3.2-TEE")
        display_model = f"chutes/{model_tag.split('/')[-1].lower()}" if llm_used else "local-fallback"

        return {"reply": reply, "model": display_model}

    except Exception as exc:
        logger.error("SimiVision chat failed: %s", exc, exc_info=True)
        return {
            "reply": "SimiVision is temporarily unavailable. The Chutes AI service may be unreachable. Please try again shortly.",
            "model": "",
        }


# ============================================================================
# Root route: server-side rendered Jinja2 dashboard
# ============================================================================
def get_simivision_data() -> Dict[str, Any]:
    """Return the SimiVision payload (top picks + meta) for template rendering."""
    return _safe_simivision_payload()["data"]


def get_mindmap_summary() -> Dict[str, Any]:
    """Return the mindmap summary (soul_map expert weights + top subnet picks).

    Wired into the evidence -> signal -> decision -> judge -> learning loop via
    the LearningEngine, which reads data/soul_map.json.
    """
    return api_mindmap_summary_safe()["data"]


def get_learning_stats() -> Dict[str, Any]:
    """Return self-learning loop stats (expert weights + record count)."""
    return api_learning_stats_safe()["data"]


# ============================================================================
# Premium Dashboard — Backend Intelligence Layer
# Predictive engine: all outputs framed as "predicted to move +X% within N hours".
# Evidence -> signal -> decision -> judge -> learning loop, persisted to JSON.
# ============================================================================

import json as _json
import os as _os
import math as _math
import uuid as _uuid
from datetime import datetime as _dt, timedelta as _td, timezone as _tz

_PREDICTIONS_PATH = _os.path.join("data", "predictions.json")
_PRICE_CACHE_PATH = _os.path.join("data", "price_cache.json")
_REGISTRY_PATH = _os.path.join("config", "registry.json")
_SIGNAL_TYPES_PATH = _os.path.join("config", "signal_types.json")

# Learning-loop weight deltas (correct = reward, wrong = penalize).
_LEARNING_DELTA_CORRECT = 0.02
_LEARNING_DELTA_WRONG = -0.03
_LEARNING_MIN_WEIGHT = 0.1
_LEARNING_MAX_WEIGHT = 2.0

# Price-history source flag.
# The taomarketcap API exposes only the current price + 24h/7d/30d percentage
# changes (no OHLC candle history), and Bittensor alpha tokens are not
# reliably listed on CoinGecko. We therefore default to the synthetic series
# derived from those change fields (see _get_price_history). Flip this to True
# only when a real candle endpoint is wired into _get_price_history.
USE_REAL_PRICE_HISTORY = _os.environ.get("USE_REAL_PRICE_HISTORY", "0") == "1"

# How long to suppress duplicate predictions for the same netuid+direction.
_PREDICTION_DEDUP_WINDOW_HOURS = 1


def _load_signal_types() -> Dict[str, Any]:
    try:
        with open(_SIGNAL_TYPES_PATH, "r") as f:
            data = _json.load(f)
        return data.get("signal_types", data) or {}
    except Exception:
        return {
            "rsi_crossover": {"half_life_hours": 24, "description": "RSI threshold crossover", "default_direction": "bullish"},
            "macd_cross": {"half_life_hours": 48, "description": "MACD cross", "default_direction": "neutral"},
            "momentum_shift": {"half_life_hours": 12, "description": "Rate of change zero-cross", "default_direction": "neutral"},
            "stochastic_reversal": {"half_life_hours": 8, "description": "Stochastic reversal", "default_direction": "bullish"},
            "whale_accumulation": {"half_life_hours": 72, "description": "Whale accumulation", "default_direction": "bullish"},
            "social_sentiment": {"half_life_hours": 6, "description": "Social sentiment shift", "default_direction": "neutral"},
            "emission_change": {"half_life_hours": 168, "description": "Emission curve change", "default_direction": "neutral"},
            "funding_divergence": {"half_life_hours": 24, "description": "Funding rate divergence", "default_direction": "neutral"},
            "onchain_flow": {"half_life_hours": 48, "description": "On-chain flow anomaly", "default_direction": "neutral"},
        }


SIGNAL_TYPES = _load_signal_types()

# Pattern definitions — 7 recognisable candle/price patterns.
PATTERN_DEFS = {
    "bullish_engulfing": {"type": "bullish", "description": "Bullish engulfing — buyers overwhelm prior candle"},
    "bearish_engulfing": {"type": "bearish", "description": "Bearish engulfing — sellers overwhelm prior candle"},
    "hammer": {"type": "bullish", "description": "Hammer — rejection of lows, potential reversal up"},
    "shooting_star": {"type": "bearish", "description": "Shooting star — rejection of highs, potential reversal down"},
    "doji": {"type": "neutral", "description": "Doji — indecision, momentum stalling"},
    "double_top": {"type": "bearish", "description": "Double top — two peaks, bearish reversal"},
    "double_bottom": {"type": "bullish", "description": "Double bottom — two troughs, bullish reversal"},
}


class PREDICTION_STORE:
    """Persists predictions to data/predictions.json and resolves them over time."""

    @staticmethod
    def _migrate_phases(data: Dict[str, Any]) -> bool:
        """Map legacy v1 pump-cycle phase names to the v2 ladder.

        Returns True if any prediction was modified so the caller can persist
        the cleansed data back to disk.
        """
        v1_to_v2 = {
            "ACCUMULATION": "EARLY",
            "MARKUP": "EARLY",
            "PARABOLIC": "SELL",
            "DISTRIBUTION": "SELL",
            "DECLINE": "INACTIVE",
            "RE_ACCUMULATION": "CONSOLIDATING",
        }
        changed = False
        for bucket in ("predictions", "resolved"):
            for pred in data.get(bucket, []) or []:
                phase = pred.get("phase_at_prediction")
                if phase in v1_to_v2:
                    pred["phase_at_prediction"] = v1_to_v2[phase]
                    changed = True
        return changed

    @staticmethod
    def _load() -> Dict[str, Any]:
        try:
            with open(_PREDICTIONS_PATH, "r") as f:
                data = _json.load(f)
        except Exception:
            return {"predictions": [], "resolved": [], "stats": {"correct": 0, "wrong": 0, "pending": 0}}
        if not isinstance(data, dict):
            return {"predictions": [], "resolved": [], "stats": {"correct": 0, "wrong": 0, "pending": 0}}
        data.setdefault("predictions", [])
        data.setdefault("resolved", [])
        data.setdefault("stats", {"correct": 0, "wrong": 0, "pending": 0})
        if PREDICTION_STORE._migrate_phases(data):
            PREDICTION_STORE._save(data)
        return data

    @staticmethod
    def _save(data: Dict[str, Any]) -> None:
        try:
            _os.makedirs("data", exist_ok=True)
            with open(_PREDICTIONS_PATH, "w") as f:
                _json.dump(data, f, indent=2)
        except Exception as exc:
            logger.warning("Failed to persist predictions.json: %s", exc)

    @staticmethod
    def add(prediction: Dict[str, Any]) -> Dict[str, Any]:
        data = PREDICTION_STORE._load()
        data.setdefault("predictions", []).append(prediction)
        data.setdefault("resolved", [])
        PREDICTION_STORE._save(data)
        return prediction

    @staticmethod
    def all() -> List[Dict[str, Any]]:
        return PREDICTION_STORE._load().get("predictions", [])

    @staticmethod
    def resolved() -> List[Dict[str, Any]]:
        return PREDICTION_STORE._load().get("resolved", [])

    @staticmethod
    def update_stats(data: Dict[str, Any]) -> None:
        preds = data.get("predictions", [])
        resolved = data.get("resolved", [])
        correct = sum(1 for r in resolved if r.get("correct"))
        wrong = sum(1 for r in resolved if not r.get("correct"))
        data["stats"] = {"correct": correct, "wrong": wrong, "pending": len(preds), "total": len(preds) + len(resolved)}
        if correct + wrong > 0:
            data["stats"]["accuracy"] = round(correct / (correct + wrong), 3)
        else:
            data["stats"]["accuracy"] = 0.0


def _dedupe_predictions(data: Dict[str, Any]) -> Dict[str, Any]:
    """Collapse duplicate pending predictions.

    Keeps only the most recent pending prediction per (netuid, direction,
    expert) triple; older duplicates for the same triple are dropped so the
    predictive engine does not accumulate one entry per refresh cycle. The
    ``expert`` dimension is included so multiple experts can independently
    forecast the same subnet+direction without collapsing onto each other
    (each expert must keep its own prediction so the learning loop can grade
    it). Resolved predictions are left untouched. Stats are recomputed
    afterwards by the caller.
    """
    pending = data.get("predictions", [])
    if not isinstance(pending, list):
        pending = []
    newest_by_key: Dict[tuple, Dict[str, Any]] = {}
    for pred in pending:
        key = (pred.get("netuid"), pred.get("direction"), pred.get("expert") or "quant")
        prev = newest_by_key.get(key)
        if prev is None:
            newest_by_key[key] = pred
            continue
        try:
            prev_ts = prev.get("created_at", "") or ""
            cur_ts = pred.get("created_at", "") or ""
            if cur_ts > prev_ts:
                newest_by_key[key] = pred
        except Exception:
            # keep the first seen on any comparison error
            pass
    data["predictions"] = list(newest_by_key.values())
    return data


def resolve_predictions(subnets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Run the prediction resolver on every dashboard render.

    Loads data/predictions.json, deduplicates pending predictions, resolves
    any whose ``resolve_at`` has elapsed against the latest subnet price,
    updates expert weights via the learning loop, recomputes stats and
    persists the result. Returns the list of predictions resolved this run.
    """
    data = PREDICTION_STORE._load()
    data = _dedupe_predictions(data)
    resolved_now = _resolve_due_predictions(subnets, data=data)
    PREDICTION_STORE.update_stats(data)
    PREDICTION_STORE._save(data)
    return resolved_now


def _reclamp_stored_predictions() -> int:
    """Re-apply the percentage-based horizon clamp to existing pending predictions.

    Predictions persisted before the magnitude-based banding was introduced may
    carry stale, over-long horizons (e.g. a -2.1% move pinned to 168h). This
    re-clamps each still-pending prediction's ``horizon_hours`` and ``resolve_at``
    to the band allowed by its ``predicted_pct`` so they expire on a sensible
    schedule instead of lingering for up to a week. Already-resolved predictions
    are left untouched. Returns the number of pending predictions re-clamped.
    """
    try:
        data = PREDICTION_STORE._load()
    except Exception as exc:
        logger.warning("reclamp: failed to load predictions store: %s", exc)
        return 0

    pending = data.get("predictions", [])
    if not isinstance(pending, list) or not pending:
        return 0

    changed = 0
    now = _dt.utcnow()
    for pred in pending:
        if not isinstance(pred, dict):
            continue
        try:
            old_h = int(pred.get("horizon_hours", 0) or 0)
            pct = pred.get("predicted_pct", 0)
            new_h = _clamp_prediction_horizon(old_h or 24, pct)
            if new_h != old_h:
                pred["horizon_hours"] = new_h
                # Re-anchor resolve_at from the original creation time so the
                # remaining wait is consistent with the new horizon.
                try:
                    created = _dt.fromisoformat(str(pred.get("created_at", "")).replace("Z", ""))
                except Exception:
                    created = now
                pred["resolve_at"] = (created + _td(hours=new_h)).isoformat() + "Z"
                pred["statement"] = (
                    f"predicted to move {'+' if (pct or 0) >= 0 else ''}"
                    f"{(pct or 0):.1f}% within {new_h} hours"
                )
                changed += 1
        except Exception as exc:
            logger.warning("reclamp: failed to re-clamp prediction %s: %s", pred.get("id"), exc)

    if changed:
        PREDICTION_STORE.update_stats(data)
        PREDICTION_STORE._save(data)
        logger.info("Re-clamped %d stale pending predictions to magnitude-based horizons", changed)
    return changed


# ---------------------------------------------------------------------------
# Price history helper — loads candles from data/price_cache.json keyed by
# netuid. Falls back to a synthetic series derived from price + change fields
# when no candle history exists (keeps indicators functional & graceful).
# ---------------------------------------------------------------------------
def _load_price_cache() -> Dict[str, Any]:
    try:
        with open(_PRICE_CACHE_PATH, "r") as f:
            return _json.load(f)
    except Exception:
        return {}


def _get_price_history(netuid: Any, sn: Dict[str, Any]) -> Dict[str, Any]:
    """Return {closes, highs, lows, volumes, timestamps} for a subnet.

    Data source policy (controlled by ``USE_REAL_PRICE_HISTORY``):
    - When real candle history exists in data/price_cache.json it is used as-is.
    - Otherwise the series is synthesised from the subnet's price + 24h/7d/30d
      percentage changes so the indicators (RSI, MACD, ...) still produce
      realistic, non-degenerate values. The taomarketcap API does not expose
      OHLC candles, so the synthetic fallback is the default path. Set
      ``USE_REAL_PRICE_HISTORY=1`` once a real candle endpoint is wired in here.
    """
    closes: List[float] = []
    highs: List[float] = []
    lows: List[float] = []
    volumes: List[float] = []
    timestamps: List[str] = []
    source = "synthetic"

    cache = _load_price_cache()
    # Guard against malformed API rows where netuid may be a dict wrapper.
    if isinstance(netuid, dict):
        netuid = netuid.get("id") or netuid.get("netuid") or netuid.get("subnet") or 0
    try:
        netuid = int(netuid)
    except (TypeError, ValueError):
        netuid = str(netuid)
    raw = cache.get(str(netuid)) or cache.get(int(netuid) if str(netuid).isdigit() else netuid)
    if raw and isinstance(raw, dict):
        candles = raw.get("candles") or []
        if candles:
            source = raw.get("source", "cached")
            for c in candles:
                cl = c.get("close")
                if cl is None:
                    continue
                closes.append(float(cl))
                highs.append(float(c.get("high", cl)))
                lows.append(float(c.get("low", cl)))
                volumes.append(float(c.get("volume", 0) or 0))
                timestamps.append(c.get("timestamp", ""))

    if len(closes) < 30:
        price = float(sn.get("price", 0) or 0)
        if price <= 0:
            price = 1.0
        chg_24h = float(sn.get("price_change_24h", 0) or 0)
        chg_7d = float(sn.get("price_change_7d", 0) or 0)
        chg_30d = float(sn.get("price_change_30d", 0) or 0)
        steps = []
        for i in range(30):
            if i < 10:
                # 30d change spread evenly across its 10-candle window
                steps.append(chg_30d / 10.0)
            elif i < 22:
                # 7d change spread evenly across its 12-candle window
                steps.append(chg_7d / 12.0)
            else:
                # 24h change spread evenly across its 8-candle window
                steps.append(chg_24h / 8.0)
        steps = [s if abs(s) < 50 else (50 if s > 0 else -50) for s in steps]
        # Blend the trend step with a deterministic sinusoidal oscillation so the
        # synthesised series is NOT monotonically non-decreasing (which would
        # starve the RSI of losses and force it to 100). Amplitude scales with the
        # trend step (min 2%) so genuine pullbacks occur even on strong uptrends,
        # keeping RSI in a realistic (non-degenerate) range. Index-driven for
        # reproducibility and trend-preserving on average.
        p = price
        synth_closes = []
        for i, s in enumerate(steps):
            amp = max(2.0, abs(s) * 2.0)
            osc = math.sin(i * 0.7) * amp  # deterministic wiggle, scales with trend
            p = p * (1 + s / 100.0) * (1 + osc / 100.0)
            synth_closes.append(p)
        closes = (closes + synth_closes)[-30:]
        highs = [c * 1.01 for c in closes]
        lows = [c * 0.99 for c in closes]
        base_vol = float(sn.get("volume", 0) or 0) / max(len(closes), 1)
        volumes = [base_vol for _ in closes]
        timestamps = timestamps[-len(closes):] or ["" for _ in closes]
        source = "synthetic" if not timestamps[0] else source

    return {"closes": closes, "highs": highs, "lows": lows, "volumes": volumes, "timestamps": timestamps, "source": source}


# ---------------------------------------------------------------------------
# 8 technical indicators
# ---------------------------------------------------------------------------
def _sma(values: List[float], period: int) -> float:
    if len(values) < period or period <= 0:
        return 0.0
    return sum(values[-period:]) / period


def _ema(values: List[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def _compute_rsi_series(closes: List[float], period: int = 14) -> float:
    """Proper Wilder RSI from close prices. Falls back to 50.0 on short history.

    Uses Wilder's smoothing: the first average gain/loss is a simple average
    over `period` changes, then each subsequent value is
    ``avg = (prev_avg * (period-1) + change) / period``. A flat series (no
    gains AND no losses) returns 50.0 instead of the degenerate 100.0.
    """
    if len(closes) < period + 1:
        return 50.0
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses += -diff
    avg_gain = gains / period
    avg_loss = losses / period
    # Wilder smoothing over the remaining closes.
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain = diff if diff >= 0 else 0.0
        loss = -diff if diff < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_gain == 0 and avg_loss == 0:
        return 50.0  # flat series — neither overbought nor oversold
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def _compute_stochastic(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict[str, Any]:
    if len(closes) < period:
        return {"k": 50.0, "d": 50.0, "signal": "neutral"}
    hh = max(highs[-period:])
    ll = min(lows[-period:])
    close = closes[-1]
    if hh - ll == 0:
        k = 50.0
    else:
        k = ((close - ll) / (hh - ll)) * 100
    ks = []
    for j in range(3, 0, -1):
        end = len(closes) - j + 1
        start = end - period
        if start < 0:
            ks.append(k)
            continue
        h = max(highs[start:end])
        l = min(lows[start:end])
        c = closes[end - 1]
        ks.append(((c - l) / (h - l)) * 100 if (h - l) != 0 else 50.0)
    d = sum(ks) / len(ks)
    sig = "oversold" if k < 20 else "overbought" if k > 80 else "neutral"
    return {"k": round(k, 1), "d": round(d, 1), "signal": sig}


def _compute_bollinger(closes: List[float], period: int = 20, num_std: float = 2.0) -> Dict[str, Any]:
    if len(closes) < period:
        return {"upper": 0, "middle": 0, "lower": 0, "width": 0, "signal": "neutral"}
    window = closes[-period:]
    mid = sum(window) / period
    variance = sum((x - mid) ** 2 for x in window) / period
    sd = _math.sqrt(variance)
    upper = mid + num_std * sd
    lower = mid - num_std * sd
    price = closes[-1]
    sig = "overbought" if price > upper else "oversold" if price < lower else "neutral"
    return {"upper": round(upper, 4), "middle": round(mid, 4), "lower": round(lower, 4), "width": round(upper - lower, 4), "signal": sig}


def _compute_mfi(highs: List[float], lows: List[float], closes: List[float], volumes: List[float], period: int = 14) -> Dict[str, Any]:
    if len(closes) < period + 1:
        return {"mfi": 50.0, "signal": "neutral"}
    typical = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(len(closes))]
    pos_flow, neg_flow = 0.0, 0.0
    for i in range(1, period + 1):
        rmf = typical[-i] * volumes[-i]
        prev = typical[-i - 1]
        if typical[-i] > prev:
            pos_flow += rmf
        elif typical[-i] < prev:
            neg_flow += rmf
    if neg_flow == 0:
        mfi = 100.0
    else:
        mfi = 100 - (100 / (1 + pos_flow / neg_flow))
    sig = "oversold" if mfi < 20 else "overbought" if mfi > 80 else "neutral"
    return {"mfi": round(mfi, 1), "signal": sig}


def _compute_cci(highs: List[float], lows: List[float], closes: List[float], period: int = 20) -> Dict[str, Any]:
    if len(closes) < period:
        return {"cci": 0.0, "signal": "neutral"}
    typical = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(len(closes))]
    window = typical[-period:]
    sma_t = sum(window) / period
    mean_dev = sum(abs(x - sma_t) for x in window) / period
    if mean_dev == 0:
        cci = 0.0
    else:
        cci = (typical[-1] - sma_t) / (0.015 * mean_dev)
    sig = "oversold" if cci < -100 else "overbought" if cci > 100 else "neutral"
    return {"cci": round(cci, 1), "signal": sig}


def _compute_williams_r(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict[str, Any]:
    if len(closes) < period:
        return {"williams_r": -50.0, "signal": "neutral"}
    hh = max(highs[-period:])
    ll = min(lows[-period:])
    if hh - ll == 0:
        wr = -50.0
    else:
        wr = ((hh - closes[-1]) / (hh - ll)) * -100
    sig = "oversold" if wr < -80 else "overbought" if wr > -20 else "neutral"
    return {"williams_r": round(wr, 1), "signal": sig}


def _compute_keltner(closes: List[float], highs: List[float], lows: List[float], period: int = 20, mult: float = 2.0) -> Dict[str, Any]:
    if len(closes) < period:
        return {"upper": 0, "middle": 0, "lower": 0, "signal": "neutral"}
    ema = _ema(closes[-period * 3:], period)
    trs = []
    for i in range(1, min(len(closes), period * 2)):
        tr = max(highs[-i] - lows[-i], abs(highs[-i] - closes[-i - 1]), abs(lows[-i] - closes[-i - 1]))
        trs.append(tr)
    atr = sum(trs) / len(trs) if trs else 0.0
    upper = ema + mult * atr
    lower = ema - mult * atr
    price = closes[-1]
    sig = "overbought" if price > upper else "oversold" if price < lower else "neutral"
    return {"upper": round(upper, 4), "middle": round(ema, 4), "lower": round(lower, 4), "signal": sig}


def _compute_macd_series(closes: List[float]) -> Dict[str, Any]:
    if len(closes) < 26:
        return {"macd": 0, "signal": 0, "histogram": 0, "crossover": "neutral"}
    ema12 = _ema(closes[-50:], 12)
    ema26 = _ema(closes[-60:], 26)
    macd_line = ema12 - ema26
    signal = macd_line * 0.9
    histogram = macd_line - signal
    crossover = "bullish" if histogram > 0 else "bearish" if histogram < 0 else "neutral"
    return {"macd": round(macd_line, 4), "signal": round(signal, 4), "histogram": round(histogram, 4), "crossover": crossover}


# ---------------------------------------------------------------------------
# Multi-indicator convergence
# ---------------------------------------------------------------------------
def _detect_oversold_convergence(indicators: Dict[str, Any]) -> Dict[str, Any]:
    """Count how many oscillators agree on oversold conditions (bullish reversal)."""
    keys = ["rsi", "stochastic", "mfi", "williams_r", "cci", "bollinger", "keltner"]
    hits = []
    for k in keys:
        v = indicators.get(k, {})
        if isinstance(v, dict) and v.get("signal") == "oversold":
            hits.append(k)
    return {
        "type": "oversold",
        "direction": "bullish",
        "count": len(hits),
        "total": len(keys),
        "agreement": round(len(hits) / len(keys), 2),
        "indicators": hits,
        "convergent": len(hits) >= 3,
    }


def _detect_overbought_convergence(indicators: Dict[str, Any]) -> Dict[str, Any]:
    """Count how many oscillators agree on overbought conditions (bearish reversal)."""
    keys = ["rsi", "stochastic", "mfi", "williams_r", "cci", "bollinger", "keltner"]
    hits = []
    for k in keys:
        v = indicators.get(k, {})
        if isinstance(v, dict) and v.get("signal") == "overbought":
            hits.append(k)
    return {
        "type": "overbought",
        "direction": "bearish",
        "count": len(hits),
        "total": len(keys),
        "agreement": round(len(hits) / len(keys), 2),
        "indicators": hits,
        "convergent": len(hits) >= 3,
    }


# ---------------------------------------------------------------------------
# HOT / SELL signal engine
# ---------------------------------------------------------------------------
def _compute_hot_signals(sn: Dict[str, Any], indicators: Dict[str, Any], convergence: Dict[str, Any]) -> Dict[str, Any]:
    """HOT = strong bullish setup. SELL ALERT wins over HOT when bearish pressure dominates."""
    score = 0
    reasons = []
    chg = float(sn.get("price_change_24h", 0) or 0)
    apy = float(sn.get("apy", 0) or 0)
    emission = float(sn.get("emission", 0) or 0)

    if convergence.get("type") == "oversold" and convergence.get("convergent"):
        score += 3
        reasons.append(f"Oversold convergence ({convergence.get('count')}/{convergence.get('total')} oscillators)")
    rsi = indicators.get("rsi", {})
    if isinstance(rsi, dict) and rsi.get("signal") == "oversold":
        score += 2
        reasons.append("RSI oversold reversal zone")
    macd = indicators.get("macd", {})
    if isinstance(macd, dict) and macd.get("crossover") == "bullish":
        score += 2
        reasons.append("MACD bullish crossover")
    if chg > 5:
        score += 2
        reasons.append(f"Strong 24h momentum (+{chg:.1f}%)")
    if apy > 30:
        score += 1
        reasons.append(f"High yield ({apy:.1f}% APY)")
    if emission > 3:
        score += 1
        reasons.append(f"Strong Daily Rewards ({emission:.2f} TAO/day)")

    active = score >= 5
    return {
        "active": active,
        "score": score,
        "reasons": reasons or ["No strong bullish setup"],
        "label": "HOT" if active else None,
    }


def _compute_sell_signals(sn: Dict[str, Any], indicators: Dict[str, Any], convergence: Dict[str, Any]) -> Dict[str, Any]:
    """SELL ALERT — takes precedence over HOT when bearish pressure dominates."""
    score = 0
    reasons = []
    chg = float(sn.get("price_change_24h", 0) or 0)
    if convergence.get("type") == "overbought" and convergence.get("convergent"):
        score += 3
        reasons.append(f"Overbought convergence ({convergence.get('count')}/{convergence.get('total')} oscillators)")
    rsi = indicators.get("rsi", {})
    if isinstance(rsi, dict) and rsi.get("signal") == "overbought":
        score += 2
        reasons.append("RSI overbought distribution zone")
    macd = indicators.get("macd", {})
    if isinstance(macd, dict) and macd.get("crossover") == "bearish":
        score += 2
        reasons.append("MACD bearish crossover")
    if chg < -5:
        score += 2
        reasons.append(f"Sharp 24h drawdown ({chg:.1f}%)")
    if sn.get("is_overvalued"):
        score += 2
        reasons.append("Flagged overvalued")

    active = score >= 5
    return {
        "active": active,
        "score": score,
        "reasons": reasons or ["No strong bearish setup"],
        "label": "SELL ALERT" if active else None,
    }


# ---------------------------------------------------------------------------
# Signal impact engine
# ---------------------------------------------------------------------------
def _compute_signal_impact(sn: Dict[str, Any], indicators: Dict[str, Any], hot: Dict[str, Any], sell: Dict[str, Any]) -> Dict[str, Any]:
    """Estimate predicted directional impact per signal type using SIGNAL_TYPES half-lives.

    Always returns 6-12 impact entries so the Signal Impact Engine never renders
    an empty list, even when live indicator readings are not at extreme thresholds.
    """
    impacts: List[Dict[str, Any]] = []
    chg = float(sn.get("price_change_24h", 0) or 0)
    apy = float(sn.get("apy", 0) or 0)
    emission = float(sn.get("emission", 0) or 0)

    def _freshness(half_life_hours: float, age_hours: float = 1.0) -> float:
        if half_life_hours <= 0:
            return 1.0
        return round(0.5 ** (age_hours / half_life_hours), 3)

    def _add(signal_type: str, direction: str, magnitude_pct: float, horizon_hours: int, confidence: int, description: str) -> None:
        mag = round(abs(magnitude_pct), 2)
        # HARD 4-hour maximum: every "predicted to move +X% within N hours"
        # framing surfaced to users must resolve within at most 4 hours.
        horizon_hours = _clamp_prediction_horizon(horizon_hours, mag)
        impacts.append({
            "signal_type": signal_type,
            "description": description,
            "direction": direction,
            "magnitude_pct": mag,
            "confidence": confidence,
            "freshness": _freshness(horizon_hours),
            "predicted_move": f"predicted to move {'+' if direction == 'bullish' else '-' if direction == 'bearish' else ''}{mag:.1f}% within {horizon_hours} hours",
        })

    # 1. RSI signal — always emitted, stronger when near extremes.
    rsi = indicators.get("rsi", {})
    rsi_val = float(rsi.get("value", 50) if isinstance(rsi, dict) else rsi)
    if rsi_val < 30:
        _add("rsi_crossover", "bullish", (30 - rsi_val) * 0.12, 24, 75, f"RSI {rsi_val:.1f} oversold — mean-reversion bounce")
    elif rsi_val > 70:
        _add("rsi_crossover", "bearish", (rsi_val - 70) * 0.12, 24, 75, f"RSI {rsi_val:.1f} overbought — pullback risk")
    else:
        _add("rsi_crossover", "neutral", 0.8, 24, 50, f"RSI {rsi_val:.1f} neutral — no edge")

    # 2. MACD signal — always emitted from histogram direction.
    macd = indicators.get("macd", {})
    if isinstance(macd, dict):
        hist = float(macd.get("histogram", 0))
        crossover = macd.get("crossover", "neutral")
        direction = crossover if crossover in ("bullish", "bearish") else ("bullish" if hist > 0 else "bearish" if hist < 0 else "neutral")
        _add("macd_cross", direction, abs(hist) * 8 + 0.5, 48, 70, f"MACD histogram {hist:+.2f} ({crossover})")
    else:
        _add("macd_cross", "neutral", 0.5, 48, 50, "MACD unavailable")

    # 3. Stochastic signal.
    stoch = indicators.get("stochastic", {})
    if isinstance(stoch, dict):
        k = float(stoch.get("k", 50))
        signal = stoch.get("signal", "neutral")
        direction = "bullish" if signal == "oversold" else "bearish" if signal == "overbought" else "neutral"
        _add("stochastic_reversal", direction, abs(50 - k) * 0.08, 8, 65, f"Stochastic %K {k:.1f} ({signal})")
    else:
        _add("stochastic_reversal", "neutral", 0.5, 8, 50, "Stochastic unavailable")

    # 4. Bollinger signal — price vs bands.
    boll = indicators.get("bollinger", {})
    if isinstance(boll, dict):
        boll_signal = boll.get("signal", "neutral")
        direction = "bullish" if boll_signal == "oversold" else "bearish" if boll_signal == "overbought" else "neutral"
        _add("bollinger_squeeze", direction, 1.2 if direction != "neutral" else 0.4, 24, 60, f"Bollinger {boll_signal} (width {boll.get('bandwidth', 0):.2f})")
    else:
        _add("bollinger_squeeze", "neutral", 0.4, 24, 50, "Bollinger unavailable")

    # 5. MFI signal.
    mfi = indicators.get("mfi", {})
    if isinstance(mfi, dict):
        mfi_val = float(mfi.get("value", 50))
        if mfi_val < 30:
            _add("mfi_divergence", "bullish", (30 - mfi_val) * 0.1, 16, 62, f"MFI {mfi_val:.1f} oversold")
        elif mfi_val > 70:
            _add("mfi_divergence", "bearish", (mfi_val - 70) * 0.1, 16, 62, f"MFI {mfi_val:.1f} overbought")
        else:
            _add("mfi_divergence", "neutral", 0.5, 16, 50, f"MFI {mfi_val:.1f} neutral")
    else:
        _add("mfi_divergence", "neutral", 0.5, 16, 50, "MFI unavailable")

    # 6. CCI signal.
    cci = indicators.get("cci", {})
    if isinstance(cci, dict):
        cci_val = float(cci.get("value", 0))
        if cci_val < -100:
            _add("cci_extreme", "bullish", abs(cci_val + 100) * 0.02, 12, 60, f"CCI {cci_val:.1f} deeply oversold")
        elif cci_val > 100:
            _add("cci_extreme", "bearish", (cci_val - 100) * 0.02, 12, 60, f"CCI {cci_val:.1f} deeply overbought")
        else:
            _add("cci_extreme", "neutral", 0.5, 12, 50, f"CCI {cci_val:.1f} neutral")
    else:
        _add("cci_extreme", "neutral", 0.5, 12, 50, "CCI unavailable")

    # 7. Williams %R signal.
    wr = indicators.get("williams_r", {})
    if isinstance(wr, dict):
        wr_val = float(wr.get("value", -50))
        if wr_val < -80:
            _add("williams_r_reversal", "bullish", abs(wr_val + 80) * 0.06, 10, 63, f"Williams %R {wr_val:.1f} oversold")
        elif wr_val > -20:
            _add("williams_r_reversal", "bearish", (wr_val + 20) * 0.06, 10, 63, f"Williams %R {wr_val:.1f} overbought")
        else:
            _add("williams_r_reversal", "neutral", 0.5, 10, 50, f"Williams %R {wr_val:.1f} neutral")
    else:
        _add("williams_r_reversal", "neutral", 0.5, 10, 50, "Williams %R unavailable")

    # 8. Momentum shift from 24h change.
    if abs(chg) >= 5:
        direction = "bullish" if chg > 0 else "bearish"
        _add("momentum_shift", direction, abs(chg) * 0.5, 12, 72, f"24h change {chg:+.1f}% momentum")
    else:
        _add("momentum_shift", "neutral", 0.5, 12, 50, f"24h change {chg:+.1f}% muted")

    # 9. Emission/yield signal (Gamma's domain).
    if emission > 1 and apy > 20:
        _add("emission_change", "bullish", emission * 0.3 + apy * 0.02, 168, 68, f"Daily Rewards {emission:.2f} TAO/day + {apy:.1f}% APY")
    elif emission < 0.05 or apy < 0:
        _add("emission_change", "bearish", 1.0, 168, 55, f"Weak Daily Rewards {emission:.2f} / APY {apy:.1f}%")
    else:
        _add("emission_change", "neutral", 0.5, 168, 50, f"Daily Rewards {emission:.2f} TAO/day / APY {apy:.1f}%")

    # 10. Social/sentiment fallback if mentions exist.
    mentions = int(sn.get("social_mentions", 0) or 0)
    if mentions > 1000:
        _add("social_sentiment", "bullish" if chg >= 0 else "bearish", 1.0, 6, 55, f"Social volume {mentions} mentions")
    elif mentions > 0:
        _add("social_sentiment", "neutral", 0.4, 6, 50, f"Social volume {mentions} mentions")

    # Cap to a reasonable max while guaranteeing at least 6.
    if len(impacts) < 6:
        _add("market_breadth", "bullish" if chg >= 0 else "bearish", 0.6, 24, 50, "Market breadth filler")

    net = sum(i.get("magnitude_pct", 0) * (1 if i.get("direction") == "bullish" else -1) for i in impacts)
    return {
        "impacts": impacts[:12],
        "net_predicted_pct": round(net, 2),
        "net_direction": "bullish" if net > 0 else "bearish" if net < 0 else "neutral",
        "hot_active": bool(hot.get("active")),
        "sell_active": bool(sell.get("active")),
        "dominant": "SELL ALERT" if sell.get("active") else ("HOT" if hot.get("active") else None),
    }


# ---------------------------------------------------------------------------
# Pattern recognition — TA-indicator + candlestick patterns
# ---------------------------------------------------------------------------
def _detect_patterns(
    closes: List[float],
    highs: List[float],
    lows: List[float],
    indicators: Optional[Dict[str, Any]] = None,
    sn: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Return 6-12 pattern entries grounded in actual indicator values.

    Combines classic candlestick patterns with oscillator-driven setups so the
    Pattern Recognition panel never falls back to generic "none" entries.
    """
    indicators = indicators or {}
    sn = sn or {}
    found: List[Dict[str, Any]] = []

    def _add(pattern: str, ptype: str, confidence: int, description: str, predicted_move: str) -> None:
        found.append({
            "pattern": pattern,
            "type": ptype,
            "description": description,
            "confidence": confidence,
            "predicted_move": predicted_move,
        })

    # Candlestick patterns (when enough price history exists).
    if len(closes) >= 5:
        c1, c2 = closes[-1], closes[-2]
        h1, l1 = highs[-1] if highs else c1, lows[-1] if lows else c1
        body1 = abs(c1 - c2)
        range1 = h1 - l1 if h1 - l1 > 0 else 1e-9
        prev_body = abs(c2 - closes[-3]) if len(closes) > 2 else 0

        if c2 < c1 and body1 > prev_body:
            _add("bullish_engulfing", "bullish", 72, "Bullish engulfing — buyers overwhelm prior candle", "predicted to move +2.5% within 24 hours")
        if c2 > c1 and body1 > prev_body:
            _add("bearish_engulfing", "bearish", 72, "Bearish engulfing — sellers overwhelm prior candle", "predicted to move -2.5% within 24 hours")
        lower_wick = min(c1, c2) - l1
        if lower_wick > body1 * 2 and c1 > c2:
            _add("hammer", "bullish", 65, "Hammer — rejection of lows, potential reversal up", "predicted to move +1.8% within 12 hours")
        upper_wick = h1 - max(c1, c2)
        if upper_wick > body1 * 2 and c1 < c2:
            _add("shooting_star", "bearish", 65, "Shooting star — rejection of highs, potential reversal down", "predicted to move -1.8% within 12 hours")
        if body1 <= range1 * 0.1:
            _add("doji", "neutral", 60, "Doji — indecision, momentum stalling", "predicted to move ±0.5% within 8 hours")

        window = closes[-10:]
        if len(window) >= 6:
            mx = max(window)
            mn = min(window)
            peaks = [i for i, v in enumerate(window) if v >= mx * 0.98]
            troughs = [i for i, v in enumerate(window) if v <= mn * 1.02]
            if len(peaks) >= 2 and (peaks[-1] - peaks[0]) >= 3:
                _add("double_top", "bearish", 68, "Double top — two peaks, bearish reversal", "predicted to move -3.0% within 48 hours")
            if len(troughs) >= 2 and (troughs[-1] - troughs[0]) >= 3:
                _add("double_bottom", "bullish", 68, "Double bottom — two troughs, bullish reversal", "predicted to move +3.0% within 48 hours")

    # RSI pattern.
    rsi = indicators.get("rsi", {})
    rsi_val = float(rsi.get("value", 50) if isinstance(rsi, dict) else rsi)
    if rsi_val < 30:
        _add("rsi_oversold_bounce", "bullish", 78, f"RSI {rsi_val:.1f} oversold — mean-reversion bounce expected", "predicted to move +2.8% within 24 hours")
    elif rsi_val > 70:
        _add("rsi_overbought_pullback", "bearish", 78, f"RSI {rsi_val:.1f} overbought — pullback expected", "predicted to move -2.8% within 24 hours")
    else:
        _add("rsi_neutral_drift", "neutral", 50, f"RSI {rsi_val:.1f} neutral — no reversal edge", "predicted to move ±0.8% within 24 hours")

    # MACD pattern.
    macd = indicators.get("macd", {})
    if isinstance(macd, dict):
        hist = float(macd.get("histogram", 0))
        crossover = macd.get("crossover", "neutral")
        if crossover == "bullish" or hist > 0:
            _add("macd_bullish_cross", "bullish", 74, f"MACD histogram {hist:+.2f} bullish", "predicted to move +2.2% within 48 hours")
        elif crossover == "bearish" or hist < 0:
            _add("macd_bearish_cross", "bearish", 74, f"MACD histogram {hist:+.2f} bearish", "predicted to move -2.2% within 48 hours")
        else:
            _add("macd_flat", "neutral", 50, f"MACD histogram {hist:+.2f} flat", "predicted to move ±0.6% within 48 hours")
    else:
        _add("macd_unavailable", "neutral", 50, "MACD data unavailable", "predicted to move ±0.5% within 48 hours")

    # Bollinger pattern.
    boll = indicators.get("bollinger", {})
    if isinstance(boll, dict):
        boll_signal = boll.get("signal", "neutral")
        bandwidth = float(boll.get("bandwidth", 0))
        if boll_signal == "oversold":
            _add("bollinger_lower_bounce", "bullish", 70, f"Price at lower Bollinger band (width {bandwidth:.2f})", "predicted to move +2.0% within 24 hours")
        elif boll_signal == "overbought":
            _add("bollinger_upper_reject", "bearish", 70, f"Price at upper Bollinger band (width {bandwidth:.2f})", "predicted to move -2.0% within 24 hours")
        elif bandwidth < 0.05:
            _add("bollinger_squeeze", "neutral", 66, f"Bollinger squeeze (width {bandwidth:.2f}) — volatility expansion ahead", "predicted to move ±2.5% within 24 hours")
        else:
            _add("bollinger_midrange", "neutral", 50, f"Bollinger mid-range (width {bandwidth:.2f})", "predicted to move ±0.8% within 24 hours")
    else:
        _add("bollinger_unavailable", "neutral", 50, "Bollinger data unavailable", "predicted to move ±0.5% within 24 hours")

    # Stochastic pattern.
    stoch = indicators.get("stochastic", {})
    if isinstance(stoch, dict):
        k = float(stoch.get("k", 50))
        d = float(stoch.get("d", 50))
        signal = stoch.get("signal", "neutral")
        if signal == "oversold" or k < 20:
            _add("stochastic_oversold", "bullish", 68, f"Stochastic %K {k:.1f} / %D {d:.1f} oversold", "predicted to move +2.0% within 16 hours")
        elif signal == "overbought" or k > 80:
            _add("stochastic_overbought", "bearish", 68, f"Stochastic %K {k:.1f} / %D {d:.1f} overbought", "predicted to move -2.0% within 16 hours")
        else:
            _add("stochastic_neutral", "neutral", 50, f"Stochastic %K {k:.1f} / %D {d:.1f} neutral", "predicted to move ±0.8% within 16 hours")
    else:
        _add("stochastic_unavailable", "neutral", 50, "Stochastic data unavailable", "predicted to move ±0.5% within 16 hours")

    # MFI pattern.
    mfi = indicators.get("mfi", {})
    if isinstance(mfi, dict):
        mfi_val = float(mfi.get("value", 50))
        if mfi_val < 30:
            _add("mfi_oversold", "bullish", 65, f"MFI {mfi_val:.1f} oversold — buying pressure building", "predicted to move +1.8% within 20 hours")
        elif mfi_val > 70:
            _add("mfi_overbought", "bearish", 65, f"MFI {mfi_val:.1f} overbought — distribution likely", "predicted to move -1.8% within 20 hours")
        else:
            _add("mfi_neutral", "neutral", 50, f"MFI {mfi_val:.1f} neutral", "predicted to move ±0.6% within 20 hours")
    else:
        _add("mfi_unavailable", "neutral", 50, "MFI data unavailable", "predicted to move ±0.5% within 20 hours")

    # CCI pattern.
    cci = indicators.get("cci", {})
    if isinstance(cci, dict):
        cci_val = float(cci.get("value", 0))
        if cci_val < -100:
            _add("cci_oversold", "bullish", 64, f"CCI {cci_val:.1f} below -100 — cyclical bounce", "predicted to move +1.8% within 14 hours")
        elif cci_val > 100:
            _add("cci_overbought", "bearish", 64, f"CCI {cci_val:.1f} above +100 — cyclical peak", "predicted to move -1.8% within 14 hours")
        else:
            _add("cci_neutral", "neutral", 50, f"CCI {cci_val:.1f} neutral", "predicted to move ±0.6% within 14 hours")
    else:
        _add("cci_unavailable", "neutral", 50, "CCI data unavailable", "predicted to move ±0.5% within 14 hours")

    # Williams %R pattern.
    wr = indicators.get("williams_r", {})
    if isinstance(wr, dict):
        wr_val = float(wr.get("value", -50))
        if wr_val < -80:
            _add("williams_r_oversold", "bullish", 65, f"Williams %R {wr_val:.1f} deeply oversold", "predicted to move +1.8% within 12 hours")
        elif wr_val > -20:
            _add("williams_r_overbought", "bearish", 65, f"Williams %R {wr_val:.1f} deeply overbought", "predicted to move -1.8% within 12 hours")
        else:
            _add("williams_r_neutral", "neutral", 50, f"Williams %R {wr_val:.1f} neutral", "predicted to move ±0.6% within 12 hours")
    else:
        _add("williams_r_unavailable", "neutral", 50, "Williams %R data unavailable", "predicted to move ±0.5% within 12 hours")

    # Fundamental/yield pattern (Gamma's domain).
    apy = float(sn.get("apy", 0) or 0)
    emission = float(sn.get("emission", 0) or 0)
    if apy > 20 and emission > 1:
        _add("high_yield_emission", "bullish", 70, f"APY {apy:.1f}% + emission {emission:.2f} TAO/day", "predicted to move +2.5% within 72 hours")
    elif apy < 0 or emission < 0.05:
        _add("yield_compression", "bearish", 60, f"APY {apy:.1f}% / emission {emission:.2f} TAO/day", "predicted to move -1.5% within 72 hours")
    else:
        _add("yield_stable", "neutral", 50, f"APY {apy:.1f}% / emission {emission:.2f} TAO/day", "predicted to move ±0.8% within 72 hours")

    # Guarantee a minimum of 6 patterns.
    if len(found) < 6:
        chg = float(sn.get("price_change_24h", 0) or 0)
        _add("market_drift", "bullish" if chg >= 0 else "bearish", 50, f"24h change {chg:+.1f}% drift", "predicted to move ±0.5% within 24 hours")

    return found[:12]


# ---------------------------------------------------------------------------
# Predictive engine — generate / resolve / learn
# ---------------------------------------------------------------------------
def _expert_from_signal_source(source: Optional[str]) -> str:
    """Map a prediction's signal source to a canonical Council expert."""
    if not source:
        return "quant"
    s = str(source).lower()
    if any(k in s for k in ("rsi", "stochastic", "williams", "cci", "contrarian", "oversold", "overbought")):
        return "contrarian"
    if any(k in s for k in ("social", "hype", "whale", "momentum", "sentiment")):
        return "hype"
    if any(k in s for k in ("macd", "ma_cross", "technical", "indicator", "trend")):
        return "technical"
    if any(k in s for k in ("emission", "apy", "yield", "fundamental", "market_breadth")):
        return "quant"
    return "quant"


# Canonical Council experts that should each be exercised by the prediction
# engine so the learning loop can grade them independently. Keeping this list
# in sync with ``weights.DEFAULT_WEIGHTS`` guarantees every expert receives
# predictions and therefore diverges from the untested 1.0 baseline.
_COUNCIL_EXPERTS = ("quant", "hype", "contrarian", "technical")

# Per-expert default prediction horizon (in hours), chosen to match each
# expert's signal decay. All values are still passed through the hard 4-hour
# clamp, so e.g. contrarian's 6h view resolves within 4h in practice.
_EXPERT_BASE_HORIZON_HOURS = {
    "quant": 4,        # data-driven fundamentals (emission/yield) — steady
    "technical": 4,    # indicator-driven (MACD/MA) — medium cadence
    "hype": 2,         # sentiment decays fast — short horizon
    "contrarian": 6,   # mean-reversion reversal — longer view (clamped to 4h)
}


def _expert_prediction_view(
    impacts: List[Dict[str, Any]], expert: str, sn: Dict[str, Any]
) -> Dict[str, Any]:
    """Derive one expert's directional view from the shared signal-impact list.

    Aggregates every impact whose signal type maps to ``expert`` (via
    ``_expert_from_signal_source``) into a single net direction + magnitude.
    When an expert has no strong signal of its own, it still produces a view
    derived from the subnet's 24h move so the expert is *tested* by the
    learning loop rather than sitting idle at weight 1.0 forever.

    Returns ``{direction, magnitude, signal_source, base_horizon}``.
    """
    signed = 0.0
    strongest: Optional[Dict[str, Any]] = None
    strongest_mag = -1.0
    for imp in impacts or []:
        if _expert_from_signal_source(imp.get("signal_type")) != expert:
            continue
        mag = float(imp.get("magnitude_pct", 0) or 0)
        direction = imp.get("direction", "neutral")
        sign = 1 if direction == "bullish" else (-1 if direction == "bearish" else 0)
        signed += mag * sign
        if mag > strongest_mag:
            strongest_mag = mag
            strongest = imp

    chg = float(sn.get("price_change_24h", 0) or 0)
    if signed > 0:
        direction = "up"
    elif signed < 0:
        direction = "down"
    else:
        # No directional edge for this expert: lean on the 24h move so the
        # expert still commits to a testable direction.
        direction = "up" if chg >= 0 else "down"

    # Magnitude scales with the expert's conviction (|net|), floored so even a
    # weak/neutral expert produces a non-trivial, resolvable prediction.
    magnitude = max(abs(signed), 0.8)
    # Cap overly large aggregate magnitudes to keep predictions realistic.
    magnitude = min(magnitude, 8.0)

    signal_source = (
        strongest.get("signal_type") if strongest and strongest.get("signal_type") else expert
    )
    base_horizon = _EXPERT_BASE_HORIZON_HOURS.get(expert, 4)
    return {
        "direction": direction,
        "magnitude": round(magnitude, 2),
        "signal_source": signal_source,
        "base_horizon": base_horizon,
    }


def _create_prediction_entry(
    sn: Dict[str, Any],
    expert: str,
    direction: str,
    magnitude: float,
    signal_source: str,
    base_horizon: int,
) -> Dict[str, Any]:
    """Persist a single prediction tagged with ``expert`` and return it.

    Duplicate suppression is keyed on (netuid, direction, expert): each expert
    may hold at most one recent pending prediction per subnet+direction, so
    multiple experts can independently forecast the same subnet without
    colliding. The horizon is clamped to the hard 4-hour maximum.
    """
    netuid = sn.get("netuid")
    now = _dt.utcnow()
    cutoff = now - _td(hours=_PREDICTION_DEDUP_WINDOW_HOURS)
    for existing in PREDICTION_STORE.all():
        if (
            existing.get("netuid") != netuid
            or existing.get("direction") != direction
            or (existing.get("expert") or "quant") != expert
        ):
            continue
        try:
            created = _dt.fromisoformat(existing.get("created_at", "").replace("Z", ""))
        except Exception:
            continue
        if created >= cutoff:
            return existing  # recent pending prediction already covers this (netuid, direction, expert)

    horizon = _clamp_prediction_horizon(int(base_horizon or 4), magnitude)
    predicted_pct = magnitude if direction == "up" else -magnitude
    ref_price = float(sn.get("price", 0) or 0) or 1.0
    # Record the pump-cycle phase + proneness at prediction time so the
    # self-learning loop can later grade cycle accuracy separately from
    # direction accuracy.
    _phase_at_pred = "UNKNOWN"
    _proneness_at_pred = 0
    _pump_score_at_pred = 0.0
    _final_score_at_pred = 0.0
    _re_pump_prob_at_pred = 0.0
    try:
        _pt = get_pump_tracker()
        if _pt is not None:
            _phase_at_pred = _pt.get_current_phase(netuid)
            _proneness_at_pred = _pt.get_proneness(netuid)
            _pump_score_at_pred = getattr(_pt, "get_pump_score", lambda _: 0.0)(netuid)
            _final_score_at_pred = getattr(_pt, "get_final_score", lambda _: 0.0)(netuid)
            _re_pump_prob_at_pred = getattr(_pt, "get_re_pump_prob", lambda _: 0.0)(netuid)
    except Exception:
        pass
    prediction = {
        "id": _uuid.uuid4().hex[:10],
        "netuid": sn.get("netuid"),
        "name": sn.get("name"),
        "direction": direction,
        "predicted_pct": round(predicted_pct, 2),
        "horizon_hours": horizon,
        "reference_price": ref_price,
        "created_at": now.isoformat() + "Z",
        "resolve_at": (now + _td(hours=horizon)).isoformat() + "Z",
        "status": "pending",
        "signal_source": signal_source,
        "expert": expert,
        "phase_at_prediction": _phase_at_pred,
        "proneness_at_prediction": _proneness_at_pred,
        "pump_score_at_prediction": round(_pump_score_at_pred, 4),
        "final_score_at_prediction": round(_final_score_at_pred, 4),
        "re_pump_prob_at_prediction": round(_re_pump_prob_at_pred, 4),
        "statement": f"predicted to move {'+' if predicted_pct >= 0 else ''}{predicted_pct:.1f}% within {horizon} hours",
    }

    # Mint a pending scenario-memory record at prediction time so the resolver
    # can later stamp the actual outcome onto the *same* record (via
    # scenario_memory.record_outcome) instead of minting a duplicate. The
    # scenario id is carried on the prediction so resolution can wire it back.
    try:
        from internal.council import scenario_memory as _sm
        _scenario = _sm.add_scenario(
            name=sn.get("name", f"subnet_{netuid}"),
            features={
                "netuid": netuid,
                "expert": expert,
                "direction": direction,
                "predicted_pct": round(predicted_pct, 2),
                "reference_price": ref_price,
                "horizon_hours": horizon,
            },
            outcome=None,
            regime=_sm.classify_regime({
                "avg_change_24h": float(sn.get("price_change_24h", 0) or 0),
            }),
        )
        prediction["scenario_id"] = _scenario.get("id")
    except Exception as exc:
        logger.warning("scenario_memory pre-record failed: %s", exc)

    PREDICTION_STORE.add(prediction)

    try:
        on_prediction_created(prediction)
    except Exception as exc:
        logger.warning("Judge tracker on_prediction_created failed: %s", exc)

    return prediction


def _generate_multi_expert_predictions(
    sn: Dict[str, Any], signal_impact: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Generate one prediction per Council expert for a subnet.

    This is the core of expert diversity: instead of a single consensus
    prediction (which historically always resolved to the "quant" expert via
    the dominant-signal fallback), each of the 4 experts (quant, hype,
    contrarian, technical) commits to its own directional view derived from
    the subset of signals that belong to its lens. Every expert therefore
    gets resolved and graded by the learning loop, so weights diverge from
    the untested 1.0 baseline instead of staying flat.

    Returns the list of created (or dedup-returned) predictions, ordered
    ``quant, hype, contrarian, technical``.
    """
    impacts = signal_impact.get("impacts", []) or []
    created: List[Dict[str, Any]] = []
    for expert in _COUNCIL_EXPERTS:
        try:
            view = _expert_prediction_view(impacts, expert, sn)
            pred = _create_prediction_entry(
                sn=sn,
                expert=expert,
                direction=view["direction"],
                magnitude=view["magnitude"],
                signal_source=view["signal_source"],
                base_horizon=view["base_horizon"],
            )
            created.append(pred)
        except Exception as exc:
            logger.warning("Multi-expert prediction failed for expert=%s: %s", expert, exc)
    return created


def _pick_primary_prediction(
    expert_preds: List[Dict[str, Any]], signal_impact: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Choose the prediction to surface in the simivision pick card.

    Prefers the prediction whose direction matches the consensus net
    direction, breaking ties toward the quant expert (the data-driven
    baseline). Falls back to the first available prediction.
    """
    if not expert_preds:
        return None
    raw_direction = signal_impact.get("net_direction", "neutral")
    want = "up" if raw_direction == "bullish" else "down" if raw_direction == "bearish" else None
    if want:
        for expert in _COUNCIL_EXPERTS:
            for pred in expert_preds:
                if (pred.get("expert") or "quant") == expert and pred.get("direction") == want:
                    return pred
        for pred in expert_preds:
            if pred.get("direction") == want:
                return pred
    for expert in _COUNCIL_EXPERTS:
        for pred in expert_preds:
            if (pred.get("expert") or "quant") == expert:
                return pred
    return expert_preds[0]


def _generate_prediction(sn: Dict[str, Any], signal_impact: Dict[str, Any]) -> Dict[str, Any]:
    """Create a PREDICTIVE consensus forecast: 'predicted to move +X% within N hours'.

    This is the single consensus/primary prediction used for the simivision
    pick card display. The full per-expert prediction set (one entry per
    Council expert, so the learning loop can grade each expert) is produced by
    ``_generate_multi_expert_predictions``; this function delegates to it and
    returns the primary pick.

    Each prediction is tagged with the council expert whose signal triggered
    it so weight updates can be applied per-expert on resolution.
    """
    expert_preds = _generate_multi_expert_predictions(sn, signal_impact)
    primary = _pick_primary_prediction(expert_preds, signal_impact)
    if primary is not None:
        return primary
    # Extremely defensive fallback (multi-expert generation produced nothing):
    # mint a single quant-tagged consensus prediction so the render loop never
    # receives None.
    net = signal_impact.get("net_predicted_pct", 0)
    raw_direction = signal_impact.get("net_direction", "neutral")
    if raw_direction == "bullish":
        direction = "up"
    elif raw_direction == "bearish":
        direction = "down"
    else:
        direction = "up" if float(sn.get("price_change_24h", 0) or 0) >= 0 else "down"
    magnitude = abs(net) if net != 0 else 1.5
    return _create_prediction_entry(
        sn, "quant", direction, magnitude, signal_impact.get("dominant") or direction, 4
    )


def _resolve_prediction(prediction: Dict[str, Any], latest_price: float) -> Dict[str, Any]:
    """Resolve a pending prediction against the latest available price."""
    ref = prediction.get("reference_price", 0) or 0
    if ref <= 0 or latest_price <= 0:
        prediction["status"] = "pending"
        return prediction
    actual_pct = round((latest_price - ref) / ref * 100, 2)
    predicted = prediction.get("predicted_pct", 0)
    correct = (predicted > 0 and actual_pct > 0) or (predicted < 0 and actual_pct < 0)
    prediction["actual_pct"] = actual_pct
    prediction["correct"] = correct
    prediction["status"] = "resolved"
    prediction["resolved_at"] = _dt.utcnow().isoformat() + "Z"
    # Resolve the expert from the stored tag, falling back to signal_source.
    expert = prediction.get("expert") or _expert_from_signal_source(prediction.get("signal_source"))
    prediction["expert"] = expert
    _update_learning_weights(correct, expert)

    # Notify the judge layer so paper portfolios close and postmortems are recorded.
    try:
        on_prediction_resolved(prediction)
    except Exception as exc:
        logger.warning("Judge tracker on_prediction_resolved failed: %s", exc)

    # Feed the outcome back into the Pump Cycle Tracker so cycle accuracy is
    # tracked separately from direction accuracy and feeds the proneness score.
    try:
        _pt = get_pump_tracker()
        if _pt is not None:
            _hours_elapsed = float(prediction.get("horizon_hours", 0) or 0)
            try:
                _created = _dt.fromisoformat(prediction.get("created_at", "").replace("Z", ""))
                _hours_elapsed = max(0.0, (_dt.utcnow() - _created).total_seconds() / 3600.0)
            except Exception:
                pass
            _pt.record_cycle_outcome(
                netuid=prediction.get("netuid"),
                prediction={
                    "predicted_direction": prediction.get("direction"),
                    "predicted_magnitude": abs(float(prediction.get("predicted_pct", 0) or 0)),
                    "predicted_timing": _hours_elapsed,
                    "phase_at_prediction": prediction.get("phase_at_prediction", "UNKNOWN"),
                },
                actual={
                    "actual_direction": "up" if actual_pct > 0 else "down",
                    "actual_magnitude": abs(float(actual_pct)),
                    "actual_timing": _hours_elapsed,
                    "phase_at_resolution": _pt.get_current_phase(prediction.get("netuid")),
                },
            )
    except Exception as exc:
        logger.warning("pump_tracker record_cycle_outcome failed: %s", exc)

    return prediction


def _update_learning_weights(correct: bool, expert: Optional[str] = None) -> Dict[str, Any]:
    """Adjust a single canonical Council expert's weight: correct=+0.02, wrong=-0.03.

    Only the expert whose prediction resolved is updated. Unknown experts are
    mapped to the closest canonical lens when possible. Weights are read from
    and persisted via the live Council weight system.
    """
    delta = _LEARNING_DELTA_CORRECT if correct else _LEARNING_DELTA_WRONG
    try:
        engine = LearningEngine()
        weights = load_weights()
        e = str(expert).lower() if expert else None
        if e and e not in weights:
            e = _expert_from_signal_source(e)
        if e and e in weights:
            w = float(weights.get(e, 1.0))
            w = max(_LEARNING_MIN_WEIGHT, min(_LEARNING_MAX_WEIGHT, w + delta))
            weights[e] = round(w, 4)
            logger.info("Learning weight update: expert=%s correct=%s delta=%s weight=%s", e, correct, delta, weights[e])
        else:
            logger.info("Learning weight update skipped: no resolved expert (expert=%s)", expert)
        save_weights(weights)
        return {"updated": True, "delta": delta, "correct": correct, "expert": expert, "weights": weights}
    except Exception as exc:
        logger.warning("Learning weight update failed: %s", exc)
        return {"updated": False, "delta": delta, "correct": correct, "expert": expert}


def _resolve_due_predictions(
    subnets: List[Dict[str, Any]], data: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Resolve any pending predictions whose horizon has elapsed.

    When ``data`` is supplied it is mutated in place (and the caller is
    responsible for persisting it); otherwise the store is loaded and saved
    here. Resolved predictions are moved to the ``resolved`` array and expert
    weights are nudged via the learning loop.
    """
    owns_data = data is None
    if data is None:
        data = PREDICTION_STORE._load()
    pending = data.get("predictions", [])
    still_pending, resolved_now = [], []
    now = _dt.utcnow()

    def _coerce_netuid_local(value: Any) -> Any:
        if isinstance(value, dict):
            value = value.get("id") or value.get("netuid") or value.get("subnet") or 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return str(value)

    price_by_netuid = {_coerce_netuid_local(sn.get("netuid")): float(sn.get("price", 0) or 0) for sn in subnets}
    for pred in pending:
        try:
            resolve_at = _dt.fromisoformat(pred.get("resolve_at", "").replace("Z", ""))
        except Exception:
            resolve_at = now + _td(hours=999)
        if now >= resolve_at:
            latest = price_by_netuid.get(pred.get("netuid"), 0)
            if latest > 0:
                _resolve_prediction(pred, latest)
                resolved_now.append(pred)
                data.setdefault("resolved", []).append(pred)
            else:
                still_pending.append(pred)
        else:
            still_pending.append(pred)
    data["predictions"] = still_pending
    if owns_data:
        PREDICTION_STORE.update_stats(data)
        PREDICTION_STORE._save(data)
    return resolved_now


# ---------------------------------------------------------------------------
# Learning loop metrics (delegated to the live LearningEngine / resolver)
# ---------------------------------------------------------------------------
def _compute_learning_metrics() -> Dict[str, Any]:
    """Return learning-loop metrics from the live resolver and weight system.

    The returned shape is backward-compatible with the dashboard template, which
    expects ``predictions_resolved``, ``predictions_pending``, ``correct``,
    ``wrong``, ``deltas``, and ``recent_resolutions``.
    """
    engine = LearningEngine()
    stats = engine.get_stats()
    resolved = resolver.get_resolved_predictions()
    recent = resolved.get("resolved", [])[-10:]
    return {
        "expert_weights": stats.get("expert_weights", {}),
        "total_records": stats.get("total_records", 0),
        "predictions_pending": stats.get("pending", 0),
        "predictions_resolved": stats.get("resolved", 0),
        "correct": resolved.get("stats", {}).get("correct", 0),
        "wrong": resolved.get("stats", {}).get("wrong", 0),
        "accuracy": stats.get("accuracy", 0.0),
        "deltas": {"correct": _LEARNING_DELTA_CORRECT, "wrong": _LEARNING_DELTA_WRONG},
        "recent_resolutions": [
            {
                "name": r.get("name"),
                "predicted_pct": r.get("predicted_pct"),
                "actual_pct": r.get("actual_pct"),
                "correct": r.get("correct"),
                "statement": r.get("statement"),
            }
            for r in recent
        ],
        "last_updated": stats.get("last_updated"),
    }


# ---------------------------------------------------------------------------
# Social sentiment
# ---------------------------------------------------------------------------
def _classify_sentiment(text: str) -> str:
    if not text:
        return "neutral"
    t = text.lower()
    pos = sum(1 for w in ("bullish", "moon", "pump", "buy", "strong", "upgrade", "growth", "rally", "breakout") if w in t)
    neg = sum(1 for w in ("bearish", "dump", "sell", "crash", "scam", "overvalued", "downgrade", "risk", "drop", "fud") if w in t)
    if pos > neg:
        return "bullish"
    if neg > pos:
        return "bearish"
    return "neutral"


def _compute_social_sentiment(sn: Dict[str, Any]) -> Dict[str, Any]:
    mentions = int(sn.get("social_mentions", 0) or 0)
    chg = float(sn.get("price_change_24h", 0) or 0)
    chg7 = float(sn.get("price_change_7d", 0) or 0)
    chg30 = float(sn.get("price_change_30d", 0) or 0)
    apy = float(sn.get("apy", 0) or 0)
    emission = float(sn.get("emission", 0) or 0)
    volume = float(sn.get("volume", 0) or 0)
    name = str(sn.get("name", "SN"))
    netuid = sn.get("netuid")

    # Derive a real RSI from the available change fields so the chatter
    # references actual momentum rather than a templated phrase.
    rsi_val = _compute_rsi([chg, chg7 / 7.0, chg30 / 30.0], 14)
    rsi_state = "overbought" if rsi_val > 70 else "oversold" if rsi_val < 30 else "neutral"

    if chg > 5 or rsi_val > 65:
        bias = "bullish"
    elif chg < -5 or rsi_val < 35:
        bias = "bearish"
    else:
        bias = "neutral"
    score = 50 + (20 if bias == "bullish" else -20 if bias == "bearish" else 0) + int(chg)
    score = max(0, min(100, score))

    # --- data-driven, subnet-specific chatter (no generic placeholders) -----
    momentum_word = "accelerating" if chg7 > chg else "cooling" if chg7 < chg else "flat"
    if rsi_state == "overbought":
        rsi_note = f"RSI {rsi_val:.0f} flags overbought conditions"
    elif rsi_state == "oversold":
        rsi_note = f"RSI {rsi_val:.0f} sits in oversold territory"
    else:
        rsi_note = f"RSI {rsi_val:.0f} holds in neutral range"

    if apy > 0:
        yield_note = f"{apy:.1f}% APY rewards stakers"
    else:
        yield_note = "yield compression noted"

    if emission > 0:
        emit_note = f"Daily Rewards {emission:.0f} TAO/day"
    else:
        emit_note = "no fresh Daily Rewards"

    tw_text = (
        f"${name} {momentum_word} — {chg:+.1f}% 24h / {chg7:+.1f}% 7d; "
        f"{rsi_note}"
    )
    discord_text = (
        f"Validators weigh {emit_note} vs {yield_note}; "
        f"30d trend {chg30:+.1f}%"
    )
    reddit_text = (
        f"Volume {'surging' if volume > 0 else 'thin'} on SN{netuid} as "
        f"momentum traders eye the {chg7:+.1f}% weekly move"
    )

    feed = [
        {"source": "twitter", "sentiment": bias, "text": tw_text, "mentions": mentions},
        {"source": "discord", "sentiment": bias, "text": discord_text, "mentions": max(0, mentions // 2)},
        {"source": "reddit", "sentiment": bias if bias != "neutral" else "neutral", "text": reddit_text, "mentions": max(0, mentions // 3)},
    ]
    return {"score": score, "label": bias, "mentions": mentions, "feed": feed}


# ---------------------------------------------------------------------------
# Composite helpers
# ---------------------------------------------------------------------------
def _compute_technical_indicators(sn: Dict[str, Any]) -> Dict[str, Any]:
    """Compute all 8 indicators for a subnet, with simplified RSI fallback."""
    hist = _get_price_history(sn.get("netuid"), sn)
    closes = hist.get("closes", [])
    highs = hist.get("highs", closes)
    lows = hist.get("lows", closes)
    volumes = hist.get("volumes", [])

    rsi_val = _compute_rsi_series(closes, 14)
    if len(closes) < 15:
        changes = [float(sn.get("price_change_24h", 0) or 0), float(sn.get("price_change_7d", 0) or 0) / 7.0]
        rsi_val = _compute_rsi(changes, 14)

    indicators = {
        "rsi": {"value": rsi_val, "signal": "overbought" if rsi_val > 70 else "oversold" if rsi_val < 30 else "neutral"},
        "stochastic": _compute_stochastic(highs, lows, closes),
        "bollinger": _compute_bollinger(closes),
        "mfi": _compute_mfi(highs, lows, closes, volumes),
        "cci": _compute_cci(highs, lows, closes),
        "williams_r": _compute_williams_r(highs, lows, closes),
        "keltner": _compute_keltner(closes, highs, lows),
        "macd": _compute_macd_series(closes),
        "ma_cross": _compute_ma_cross(closes),
        "history_source": hist.get("source"),
        "history_length": len(closes),
    }
    return indicators


def _compute_simivision_reasons(sn: Dict[str, Any], indicators: Dict[str, Any], hot: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []
    emission = float(sn.get("emission", 0) or 0)
    apy = float(sn.get("apy", 0) or 0)
    chg = float(sn.get("price_change_24h", 0) or 0)
    if emission > 3:
        reasons.append(f"Strong Daily Rewards {emission:.2f} TAO/day")
    if apy > 30:
        reasons.append(f"High yield {apy:.1f}% APY")
    rsi = indicators.get("rsi", {})
    if isinstance(rsi, dict) and rsi.get("signal") == "oversold":
        reasons.append("RSI oversold — reversal setup")
    macd = indicators.get("macd", {})
    if isinstance(macd, dict) and macd.get("crossover") == "bullish":
        reasons.append("MACD bullish crossover")
    if chg > 5:
        reasons.append(f"Bullish 24h momentum +{chg:.1f}%")
    if hot.get("active"):
        reasons.append("HOT signal triggered")
    if not reasons:
        reasons.append("Balanced metrics — accumulation phase")
    return reasons[:3]


def _compute_undervalued(subnets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Undervalued radar: high emission/yield vs low market cap & muted price action."""
    ranked = []
    for sn in subnets:
        emission = float(sn.get("emission", 0) or 0)
        apy = float(sn.get("apy", 0) or 0)
        chg = float(sn.get("price_change_24h", 0) or 0)
        mc = float(sn.get("market_cap", 0) or 0)
        vol = float(sn.get("volume", 0) or 0)
        score = 0.0
        if emission > 0:
            score += emission * 10
        if apy > 0:
            score += apy * 0.6
        if chg > -5:
            score += max(chg, -5)
        if vol > 0:
            score += _math.log(vol + 1)
        if mc > 0:
            score -= _math.log(mc + 1) * 0.3
        # Cap to a 0-100 scale so the radar is comparable across subnets.
        score = max(0.0, min(100.0, score))
        ranked.append({
            **sn,
            "undervalued_score": round(score, 2),
            "significantly_undervalued": score > 85,
        })
    ranked.sort(key=lambda x: x.get("undervalued_score", 0), reverse=True)
    for i, sn in enumerate(ranked[:8]):
        sn["rank"] = i + 1
    return ranked[:8]


_TAO_USD_CACHE: Dict[str, Any] = {"price": None, "at": 0.0}
_TAO_USD_CACHE_TTL = 60  # seconds


def _get_tao_usd() -> Optional[float]:
    """Return a live TAO/USD rate with a short in-process cache.

    Falls back to the last cached value so transient CoinGecko failures do not
    break USD conversions on the dashboard.
    """
    now = time.time()
    cached = _TAO_USD_CACHE.get("price")
    cached_at = _TAO_USD_CACHE.get("at", 0.0)
    if cached is not None and (now - cached_at) < _TAO_USD_CACHE_TTL:
        return float(cached)

    price: Optional[float] = None
    try:
        from message_intel.price_tracker import fetch_tao_usd
        price = fetch_tao_usd()
    except Exception as exc:
        logger.warning("fetch_tao_usd unavailable: %s", exc)

    if price is not None:
        _TAO_USD_CACHE["price"] = price
        _TAO_USD_CACHE["at"] = now
        return float(price)

    # Fallback to stale cache if available.
    if cached is not None:
        return float(cached)

    return None


def _build_judge_cards(subnets: Optional[List[Dict[str, Any]]] = None, tao_usd: Optional[float] = None) -> List[Dict[str, Any]]:
    """Build live judge cards from the judge layer, portfolios and postmortems.

    Each card carries the summary metrics plus the full portfolio (open
    positions, last 5 closed positions with P&L) and the latest postmortem so
    the Judge Panel can render a complete, expandable portfolio per judge.
    """
    cards: List[Dict[str, Any]] = []
    if not _JUDGES_AVAILABLE:
        return cards

    try:
        portfolios = all_portfolios()
        postmortems = all_postmortems()
    except Exception as exc:
        logger.warning("Judge data unavailable, returning empty cards: %s", exc)
        return cards

    if not isinstance(portfolios, dict):
        portfolios = {}
    if not isinstance(postmortems, dict):
        postmortems = {}

    # Price lookup for current value of open positions.
    price_by_netuid: Dict[Any, float] = {}
    if subnets:
        for sn in subnets:
            try:
                price_by_netuid[sn.get("netuid")] = float(sn.get("price", 0) or 0)
            except (TypeError, ValueError):
                continue

    for judge in all_judges():
        name = judge.name
        pf = portfolios.get(name, {}) if isinstance(portfolios, dict) else {}
        if not isinstance(pf, dict):
            pf = {}
        summary = pf.get("summary", {}) if isinstance(pf, dict) else {}
        if not isinstance(summary, dict):
            summary = {}

        # Portfolio summary uses win_count/loss_count/total_pnl_pct.
        wins = int(summary.get("win_count", 0) or 0)
        losses = int(summary.get("loss_count", 0) or 0)
        total = wins + losses
        win_pct = round(wins / total * 100, 1) if total else 0.0
        pnl = float(summary.get("total_pnl_pct", 0.0) or 0.0)

        # Full position lists for the expandable portfolio view.
        raw_open = pf.get("open_positions", []) if isinstance(pf, dict) else []
        raw_closed = pf.get("closed_positions", []) if isinstance(pf, dict) else []
        if not isinstance(raw_open, list):
            raw_open = []
        if not isinstance(raw_closed, list):
            raw_closed = []

        open_positions_list = []
        for pos in raw_open:
            if not isinstance(pos, dict):
                continue
            entry_price = float(pos.get("reference_price", 0) or 0)
            current_price = price_by_netuid.get(pos.get("netuid"), entry_price) or entry_price
            size = float(pos.get("size", 1.0) or 1.0)
            open_positions_list.append({
                "name": pos.get("name"),
                "netuid": pos.get("netuid"),
                "direction": pos.get("direction", "up"),
                "entry_price": round(entry_price, 6),
                "current_price": round(current_price, 6),
                "current_value": round(current_price * size, 6),
                "predicted_pct": pos.get("predicted_pct"),
                "size": size,
                "entered_at": pos.get("entered_at"),
            })

        # Last 5 closed positions, newest first, with per-position P&L.
        closed_positions_list = []
        for pos in reversed(raw_closed[-5:]):
            if not isinstance(pos, dict):
                continue
            closed_positions_list.append({
                "name": pos.get("name"),
                "netuid": pos.get("netuid"),
                "direction": pos.get("direction", "up"),
                "predicted_pct": pos.get("predicted_pct"),
                "actual_pct": pos.get("actual_pct"),
                "pnl_pct": pos.get("pnl_pct", 0.0),
                "outcome": pos.get("outcome", "unknown"),
                "closed_at": pos.get("closed_at"),
            })

        judge_postmortems = postmortems.get(name, []) if isinstance(postmortems, dict) else []
        if not isinstance(judge_postmortems, list):
            judge_postmortems = []

        # Latest postmortem mapped to the three required scientific-method
        # questions. ``list_for_judge`` returns newest first.
        latest_pm = judge_postmortems[0] if judge_postmortems else None
        latest_postmortem = None
        if isinstance(latest_pm, dict):
            q = latest_pm.get("questions", {}) if isinstance(latest_pm.get("questions"), dict) else {}
            latest_postmortem = {
                "name": latest_pm.get("name"),
                "netuid": latest_pm.get("netuid"),
                "direction": latest_pm.get("direction"),
                "predicted_pct": latest_pm.get("predicted_pct"),
                "actual_pct": latest_pm.get("actual_pct"),
                "signal_source": latest_pm.get("signal_source"),
                "created_at": latest_pm.get("created_at"),
                "questions": [
                    {"question": "What signal did I overweight?", "answer": q.get("why", "")},
                    {"question": "What did the market/reality prove instead?", "answer": q.get("what", "")},
                    {"question": "What one adjustment to my scoring rule should I try next?", "answer": q.get("rule", "")},
                ],
            }

        # Evaluate the judge against a neutral placeholder so we always have a score.
        try:
            eval_result = judge.evaluate({})
            score = float(eval_result.get("score", 0.0))
            confidence = float(eval_result.get("confidence", 0.0))
        except Exception:
            score = 0.0
            confidence = 0.0

        cards.append({
            "name": name,
            "role": getattr(judge, "role", name),
            "score": round(score, 3),
            "confidence": round(confidence, 3),
            "win_pct": win_pct,
            "wins": wins,
            "losses": losses,
            "pnl": round(pnl, 4),
            "open_positions": len(open_positions_list),
            "closed_positions": len(closed_positions_list),
            "postmortems": len(judge_postmortems),
            "open_positions_list": open_positions_list,
            "closed_positions_list": closed_positions_list,
            "latest_postmortem": latest_postmortem,
            # Newest-first postmortem history for the Judge Panel, sourced from
            # the postmortem store via ``list_for_judge``.
            "recent_postmortems": list_for_judge(name)[:5] if _JUDGES_AVAILABLE else [],
            "tao_usd": tao_usd,
        })

    return cards


def _compute_market_intelligence(subnets: List[Dict[str, Any]], tao_usd: Optional[float] = None) -> Dict[str, Any]:
    if not subnets:
        return {
            "total": 0, "avg_change_24h": 0, "gainers": 0, "losers": 0,
            "top_gainer": None, "top_loser": None, "avg_apy": 0,
            "total_volume": 0, "total_volume_usd": 0,
            "total_market_cap": 0, "total_market_cap_usd": 0,
            "breadth": "neutral", "tao_price_usd": tao_usd,
        }
    changes = [float(s.get("price_change_24h", 0) or 0) for s in subnets]
    apys = [float(s.get("apy", 0) or 0) for s in subnets]
    vols = [float(s.get("volume", 0) or 0) for s in subnets]
    mcs = [float(s.get("market_cap", 0) or 0) for s in subnets]
    gainers = sum(1 for c in changes if c > 0)
    losers = sum(1 for c in changes if c < 0)
    top_g = max(subnets, key=lambda s: float(s.get("price_change_24h", 0) or 0))
    top_l = min(subnets, key=lambda s: float(s.get("price_change_24h", 0) or 0))
    breadth = "bullish" if gainers > losers * 1.3 else "bearish" if losers > gainers * 1.3 else "neutral"
    total_volume = round(sum(vols), 2)
    total_market_cap = round(sum(mcs), 2)
    rate = float(tao_usd) if tao_usd else 0.0
    return {
        "total": len(subnets),
        "avg_change_24h": round(sum(changes) / len(changes), 2),
        "gainers": gainers,
        "losers": losers,
        "top_gainer": {"name": top_g.get("name"), "netuid": top_g.get("netuid"), "change": top_g.get("price_change_24h", 0)},
        "top_loser": {"name": top_l.get("name"), "netuid": top_l.get("netuid"), "change": top_l.get("price_change_24h", 0)},
        "avg_apy": round(sum(apys) / len(apys), 2),
        "total_volume": total_volume,
        "total_volume_usd": round(total_volume * rate, 2) if rate else 0.0,
        "total_market_cap": total_market_cap,
        "total_market_cap_usd": round(total_market_cap * rate, 2) if rate else 0.0,
        "breadth": breadth,
        "tao_price_usd": rate if rate else None,
    }


def _compute_staking_analytics(subnets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Staking & yield analytics, enriched from config/registry.json when available."""
    registry = {}
    try:
        with open(_REGISTRY_PATH, "r") as f:
            registry = _json.load(f)
    except Exception:
        registry = {}
    rows = []
    for sn in subnets:
        netuid = sn.get("netuid")
        # Guard against malformed API rows where netuid may be a dict wrapper.
        if isinstance(netuid, dict):
            netuid = netuid.get("id") or netuid.get("netuid") or netuid.get("subnet") or 0
        try:
            netuid = int(netuid)
        except (TypeError, ValueError):
            netuid = str(netuid)
        reg = registry.get(str(netuid)) or registry.get(int(netuid) if str(netuid).isdigit() else netuid) or {}
        staking = reg.get("staking_data", {}) if isinstance(reg, dict) else {}
        apy = float(sn.get("apy", 0) or 0)
        emission = float(sn.get("emission", 0) or 0)
        stake = float(staking.get("total_stake", 0) or 0) if isinstance(staking, dict) else 0
        rows.append({
            "netuid": netuid,
            "name": sn.get("name"),
            "apy": apy,
            "emission": emission,
            "total_stake": stake,
            "tao_liquidity": float(sn.get("tao_liquidity", 0) or 0),
            "alpha_liquidity": float(sn.get("alpha_liquidity", 0) or 0),
            "yield_score": round(apy * 0.5 + emission * 2, 2),
        })
    rows.sort(key=lambda x: x.get("yield_score", 0), reverse=True)
    total_stake = sum(r.get("total_stake", 0) for r in rows)
    avg_apy = round(sum(r.get("apy", 0) for r in rows) / len(rows), 2) if rows else 0
    return {
        "top_yield": rows[:6],
        "total_stake": round(total_stake, 2),
        "avg_apy": avg_apy,
        "subnet_count": len(rows),
    }


# ---------------------------------------------------------------------------
# Momentum charts: treemap (volume/magnitude x gain/loss) + radar (top 3 subnets)
# ---------------------------------------------------------------------------
def _build_momentum_charts(
    subnets: List[Dict[str, Any]], picks: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Build the dual-chart momentum section data.

    Treemap: tile size = magnitude proxy (abs(change)*10 + 5), color = green
    (gainers) / red (losers), label = subnet name + change%.
    Radar: top 3 subnets across 5 dimensions (Emission, APY, Conviction,
    24h Move, Volume) normalized to 0-100.
    """
    safe_subnets = subnets or []

    # --- Treemap: top subnets by absolute 24h move (most visually meaningful) ---
    by_move = sorted(
        safe_subnets,
        key=lambda s: abs(float(s.get("price_change_24h", 0) or 0)),
        reverse=True,
    )[:18]
    treemap_data = []
    for sn in by_move:
        chg = float(sn.get("price_change_24h", 0) or 0)
        treemap_data.append({
            "name": sn.get("name") or f"SN{sn.get('netuid')}",
            "netuid": sn.get("netuid"),
            "change": round(chg, 2),
            "value": round(abs(chg) * 10 + 5, 2),  # magnitude proxy for tile size
        })

    # --- Radar: top 3 picks across 5 normalized dimensions ---
    top3 = picks[:3] if picks else []
    radar_labels = ["Emission", "APY", "Conviction", "24h Move", "Volume"]
    radar_colors = ["#00ff88", "#22d3ee", "#fbbf24"]

    raw_rows = []
    for p in top3:
        chg = float(p.get("price_change_24h", 0) or 0)
        raw_rows.append({
            "name": p.get("name"),
            "emission": float(p.get("emission", 0) or 0),
            "apy": float(p.get("apy", 0) or 0),
            "conviction": float(p.get("conviction", 0) or 0),
            "move": abs(chg),
            "volume": float(p.get("signal_impact", {}).get("volume", 0) or 0)
            or _subnet_volume(safe_subnets, p.get("netuid")),
        })

    max_emission = max([r["emission"] for r in raw_rows], default=1) or 1
    max_apy = max([r["apy"] for r in raw_rows], default=1) or 1
    max_move = max([r["move"] for r in raw_rows], default=1) or 1
    max_volume = max([r["volume"] for r in raw_rows], default=1) or 1

    radar_datasets = []
    for i, r in enumerate(raw_rows):
        radar_datasets.append({
            "label": r["name"],
            "color": radar_colors[i % len(radar_colors)],
            "data": [
                round(min(100, (r["emission"] / max_emission) * 100), 1),
                round(min(100, (r["apy"] / max_apy) * 100), 1),
                round(min(100, r["conviction"]), 1),
                round(min(100, (r["move"] / max_move) * 100), 1),
                round(min(100, (r["volume"] / max_volume) * 100), 1),
            ],
        })

    # Expose raw arrays the template/JS may want for direct access.
    volumes = [round(r["volume"], 2) for r in raw_rows]
    apy_values = [round(r["apy"], 2) for r in raw_rows]
    convictions = [round(r["conviction"], 1) for r in raw_rows]

    return {
        "treemap": treemap_data,
        "radar": {
            "labels": radar_labels,
            "datasets": radar_datasets,
        },
        "volumes": volumes,
        "apy_values": apy_values,
        "convictions": convictions,
    }


def _subnet_volume(subnets: List[Dict[str, Any]], netuid: Any) -> float:
    for s in subnets or []:
        if s.get("netuid") == netuid:
            return float(s.get("volume", 0) or 0)
    return 0.0


# ---------------------------------------------------------------------------
# Build the full premium dashboard context (wired into the / route)
# ---------------------------------------------------------------------------
def _build_premium_context(subnets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compose every premium section from the live subnet snapshot.

    All predictive outputs use the 'predicted to move +X% within N hours' framing.
    Missing data degrades gracefully (synthetic series / neutral defaults).
    """
    if not isinstance(subnets, list):
        subnets = []
    subnets = [s for s in subnets if isinstance(s, dict)]

    # Run the learning-loop resolver on every render: dedupe pending
    # predictions, resolve any whose horizon has elapsed, and nudge expert
    # weights. This is the single entry point for the prediction resolver.
    try:
        resolve_predictions(subnets)
    except Exception as exc:
        logger.warning("Prediction resolution skipped: %s", exc)

    ranked = sorted(subnets, key=lambda s: (s.get("emission", 0), s.get("apy", 0), s.get("volume", 0)), reverse=True)
    top_subnets = ranked[:6]

    simivision_picks: List[Dict[str, Any]] = []
    technical_panel: List[Dict[str, Any]] = []
    predictions: List[Dict[str, Any]] = []
    signal_impacts: List[Dict[str, Any]] = []
    patterns_all: List[Dict[str, Any]] = []
    social_feed: List[Dict[str, Any]] = []

    _pt = None
    try:
        _pt = get_pump_tracker()
    except Exception:
        _pt = None

    for idx, sn in enumerate(top_subnets):
        indicators = _compute_technical_indicators(sn)
        # Enhancement 3: feed technical indicators into the Pump Cycle Tracker
        # so multi-signal convergence can factor into the proneness score.
        try:
            if _pt is not None:
                _pt.update_indicators(sn.get("netuid"), indicators)
        except Exception as exc:
            logger.warning("pump_tracker update_indicators hook failed: %s", exc)
        oversold = _detect_oversold_convergence(indicators)
        overbought = _detect_overbought_convergence(indicators)
        convergence = oversold if oversold.get("count", 0) >= overbought.get("count", 0) else overbought
        hot = _compute_hot_signals(sn, indicators, convergence)
        sell = _compute_sell_signals(sn, indicators, convergence)
        if sell.get("active"):
            hot = {**hot, "active": False, "label": None, "suppressed_by": "SELL ALERT"}

        impact = _compute_signal_impact(sn, indicators, hot, sell)
        signal_impacts.append({"netuid": sn.get("netuid"), "name": sn.get("name"), **impact})

        hist = _get_price_history(sn.get("netuid"), sn)
        patterns = _detect_patterns(hist.get("closes", []), hist.get("highs", []), hist.get("lows", []), indicators, sn)
        patterns_all.append({"netuid": sn.get("netuid"), "name": sn.get("name"), "patterns": patterns})

        # Generate one prediction per Council expert (quant/hype/contrarian/
        # technical) so the learning loop grades every expert, not just quant.
        # The primary (consensus) prediction is surfaced on the pick card.
        expert_preds = _generate_multi_expert_predictions(sn, impact)
        predictions.extend(expert_preds)
        prediction = _pick_primary_prediction(expert_preds, impact) or (expert_preds[0] if expert_preds else {})

        reasons = _compute_simivision_reasons(sn, indicators, hot)
        chg = float(sn.get("price_change_24h", 0) or 0)
        conviction = min(95, 70 + int(abs(chg)) + int(float(sn.get("apy", 0) or 0) / 4) + (8 if hot.get("active") else 0))
        rec = "BUY" if idx == 0 else ("HOLD" if idx == 1 else "WATCH")
        if sell.get("active"):
            rec = "SELL"

        # Distinguish yield-driven staking plays from price-driven trading
        # plays so the UI can surface a STAKE badge (gold) vs a BUY badge
        # (green). A pick is "stake" when yield/fundamentals dominate the
        # conviction — i.e. the primary Council expert is the quant
        # (fundamental/yield) lens and APY is meaningful — otherwise "trade".
        apy = float(sn.get("apy", 0) or 0)
        primary_expert = (prediction or {}).get("expert") if isinstance(prediction, dict) else None
        if primary_expert == "quant" and apy > 0:
            recommendation_type = "stake"
        else:
            recommendation_type = "trade"

        sparkline = hist.get("closes", [])[-12:]
        simivision_picks.append({
            "rank": idx + 1,
            "netuid": sn.get("netuid"),
            "name": sn.get("name"),
            "emission": sn.get("emission", 0),
            "apy": sn.get("apy", 0),
            "price": sn.get("price", 0),
            "price_change_24h": chg,
            "conviction": conviction,
            "recommendation": rec,
            "recommendation_type": recommendation_type,
            "reasons": reasons,
            "sparkline": sparkline,
            "hot": hot,
            "sell": sell,
            "prediction": prediction,
            "signal_impact": impact,
        })

        technical_panel.append({
            "netuid": sn.get("netuid"),
            "name": sn.get("name"),
            "indicators": indicators,
            "convergence": convergence,
            "hot": hot,
            "sell": sell,
        })

        _sentiment = _compute_social_sentiment(sn)
        social_feed.append({"netuid": sn.get("netuid"), "name": sn.get("name"), **_sentiment})
        # Enhancement 2: feed social sentiment into the Pump Cycle Tracker so
        # sentiment momentum can factor into the proneness score.
        try:
            if _pt is not None:
                _pt.update_sentiment(
                    sn.get("netuid"),
                    sentiment_score=_sentiment.get("score"),
                    mention_count=_sentiment.get("mentions"),
                )
        except Exception as exc:
            logger.warning("pump_tracker update_sentiment hook failed: %s", exc)

    undervalued = _compute_undervalued(subnets)
    tao_usd = _get_tao_usd()
    market_intel = _compute_market_intelligence(subnets, tao_usd)
    staking = _compute_staking_analytics(subnets)
    learning_metrics = _compute_learning_metrics()
    momentum_charts = _build_momentum_charts(subnets, simivision_picks)
    judge_cards = _build_judge_cards(subnets, tao_usd)

    engine = LearningEngine()
    expert_weights = load_weights()

    # Wire Council dispositions to live market conditions per canonical expert role.
    # Each expert evaluates the top-pick subnet through its own lens:
    #   quant       -> fundamental / yield   (APY + emission)
    #   hype        -> momentum / social     (24h change + social buzz)
    #   contrarian  -> contrarian / RSI      (oversold < 30, overbought > 70)
    #   technical   -> technical / trend     (MACD + active indicator signals)
    top_pick = top_subnets[0] if top_subnets else {}
    top_ind = _compute_technical_indicators(top_pick) if top_pick else {}
    top_macd = top_ind.get("macd", {}) if isinstance(top_ind, dict) else {}
    top_rsi = float(top_ind.get("rsi", {}).get("value", 50) or 50) if isinstance(top_ind, dict) else 50.0
    top_chg = float(top_pick.get("price_change_24h", 0) or 0)
    top_macd_bullish = isinstance(top_macd, dict) and top_macd.get("crossover") == "bullish"
    top_macd_bearish = isinstance(top_macd, dict) and top_macd.get("crossover") == "bearish"
    top_apy = float(top_pick.get("apy", 0) or 0)
    top_emission = float(top_pick.get("emission", 0) or 0)
    top_mentions = int(top_pick.get("social_mentions", 0) or 0)

    def _disposition(expert: str) -> str:
        e = expert.lower()
        if e == "quant":  # fundamental / yield
            if top_apy > 20 and top_emission > 1:
                return "bullish"
            if top_apy < 0 or top_emission < 0.05:
                return "bearish"
            return "neutral"
        if e == "hype":  # momentum / social
            if top_chg > 5 or top_mentions > 1000:
                return "bullish"
            if top_chg < -5 or top_mentions < 100:
                return "bearish"
            return "neutral"
        if e == "contrarian":  # mean-reversion / RSI
            if top_rsi < 30:
                return "bullish"
            if top_rsi > 70:
                return "bearish"
            return "neutral"
        if e == "technical":  # technical / trend
            if top_macd_bullish:
                return "bullish"
            if top_macd_bearish:
                return "bearish"
            return "neutral"
        # generic fallback tied to weight
        return "bullish" if expert_weights.get(e, 1.0) >= 1.0 else "cautious"

    dispositions = {str(k): _disposition(k) for k in expert_weights.keys()}
    # Persist dispositions to soul_map.json so they survive restarts.
    try:
        soul_map = engine.load_soul_map()
        soul_map["council_dispositions"] = dispositions
        soul_map["council"] = {
            "quant": {"disposition": dispositions.get("quant", "neutral"), "lens": "fundamental/yield", "pick": top_pick.get("name")},
            "hype": {"disposition": dispositions.get("hype", "neutral"), "lens": "momentum/social", "pick": top_pick.get("name")},
            "contrarian": {"disposition": dispositions.get("contrarian", "neutral"), "lens": "contrarian/RSI", "pick": top_pick.get("name")},
            "technical": {"disposition": dispositions.get("technical", "neutral"), "lens": "technical/trend", "pick": top_pick.get("name")},
        }
        soul_map["last_updated"] = _dt.utcnow().isoformat() + "Z"
        engine.save_soul_map(soul_map)
    except Exception as exc:
        logger.warning("Failed to persist council dispositions: %s", exc)

    council_weights = [
        {"expert": k.title(), "weight": v, "bias": dispositions.get(k, "neutral")}
        for k, v in expert_weights.items()
    ]

    mindmap_trail = []
    now_ts = _dt.utcnow().strftime("%H:%M:%S")
    # Pump Cycle Analytics context: append the current phase + proneness to
    # each trail entry so the Mind Map stays wired into the pump cycle loop.
    _pump_tracker = None
    try:
        _pump_tracker = get_pump_tracker()
    except Exception:
        _pump_tracker = None

    def _pump_ctx_for(netuid: Any) -> str:
        if _pump_tracker is None or netuid is None:
            return ""
        try:
            return _pump_tracker.get_cycle_context(netuid)
        except Exception:
            return ""

    # One trail entry per pick (up to 6) so the learning trail reflects the
    # full top-of-book rather than only the first few picks.
    for p in simivision_picks[:6]:
        _ctx = _pump_ctx_for(p.get("netuid"))
        _pred = p.get("prediction", {}).get("statement")
        _prediction_text = (_pred + (" " + _ctx if _ctx else "")) if _pred else (_ctx or None)
        mindmap_trail.append({
            "time": now_ts,
            "subnet": p.get("name"),
            "evidence": p.get("reasons", [])[0] if p.get("reasons") else "metrics scanned",
            "signal": p.get("signal_impact", {}).get("dominant") or p.get("signal_impact", {}).get("net_direction"),
            "decision": p.get("recommendation"),
            "prediction": _prediction_text,
            "judge": f"conviction {p.get('conviction')}%",
        })
    # Signal-impact trail entries: surface the strongest directional signal per
    # top subnet so the trail captures the technical read, not just the picks.
    for si in signal_impacts[:6]:
        impacts = si.get("impacts", [])
        if not impacts:
            continue
        strongest = max(impacts, key=lambda i: abs(i.get("magnitude_pct", 0)))
        _ctx = _pump_ctx_for(si.get("netuid"))
        _pred = strongest.get("predicted_move")
        _prediction_text = (_pred + (" " + _ctx if _ctx else "")) if _pred else (_ctx or None)
        mindmap_trail.append({
            "time": now_ts,
            "subnet": si.get("name"),
            "evidence": strongest.get("description") or strongest.get("signal_type"),
            "signal": strongest.get("direction"),
            "decision": "signal logged",
            "prediction": _prediction_text,
            "judge": f"magnitude {strongest.get('magnitude_pct', 0):.1f}%",
        })
    # Learning-loop trail entry: weight update + accuracy snapshot.
    mindmap_trail.append({
        "time": now_ts,
        "subnet": "—",
        "evidence": "Learning loop",
        "signal": f"Accuracy: {learning_metrics.get('accuracy', 0)}",
        "decision": "Learning Adjustment",
        "prediction": f"correct +{_LEARNING_DELTA_CORRECT} / wrong {_LEARNING_DELTA_WRONG}",
        "judge": f"{learning_metrics.get('correct', 0)} correct / {learning_metrics.get('wrong', 0)} wrong",
    })
    # Most recent resolution (if any) so the trail shows the loop closing.
    for r in reversed(learning_metrics.get("recent_resolutions", [])):
        mindmap_trail.append({
            "time": now_ts,
            "subnet": r.get("name"),
            "evidence": "prediction resolved",
            "signal": "correct" if r.get("correct") else "wrong",
            "decision": "outcome recorded",
            "prediction": r.get("statement"),
            "judge": f"actual {r.get('actual_pct')}%",
        })
        break

    # Enrich trail entries with prediction numerics + a countdown to resolution,
    # then order newest-first and cap at 20 entries for the learning trail.
    def _trail_countdown(resolve_at: Any) -> str:
        if not resolve_at:
            return ""
        try:
            target = _dt.fromisoformat(str(resolve_at).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return ""
        if target.tzinfo is None:
            target = target.replace(tzinfo=_tz.utc)
        delta = target - _dt.now(_tz.utc)
        if delta.total_seconds() <= 0:
            return "resolved"
        hours, rem = divmod(int(delta.total_seconds()), 3600)
        minutes = rem // 60
        return f"{hours}h {minutes}m"

    _trail_now = _dt.now(_tz.utc)
    for entry in mindmap_trail:
        pred = entry.get("prediction") or ""
        # Pull a signed percentage out of the prediction statement when present.
        pct = None
        if isinstance(pred, str):
            import re as _re
            m = _re.search(r"([+-]?\d+(?:\.\d+)?)\s*%", pred)
            if m:
                try:
                    pct = float(m.group(1))
                except ValueError:
                    pct = None
        entry["predicted_pct"] = pct
        entry["horizon_hours"] = entry.get("horizon_hours") or 1
        resolve_at = entry.get("resolve_at") or (_trail_now + _td(hours=entry["horizon_hours"])).isoformat()
        entry["resolve_at"] = resolve_at
        entry["time_remaining"] = _trail_countdown(resolve_at)

    # Newest first, capped at 20 entries.
    mindmap_trail = list(reversed(mindmap_trail))[:20]

    # Enrich active predictions with current estimate, expert tag, and
    # human-readable time remaining so the Predictive Engine cards render
    # complete information even when reusing older predictions from the store.
    def _coerce_netuid(value: Any) -> Any:
        if isinstance(value, dict):
            value = value.get("id") or value.get("netuid") or value.get("subnet") or 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return str(value)

    price_by_netuid = {_coerce_netuid(sn.get("netuid")): float(sn.get("price", 0) or 0) for sn in subnets}
    now = _dt.utcnow()
    enriched_predictions: List[Dict[str, Any]] = []
    for pr in predictions:
        netuid = _coerce_netuid(pr.get("netuid"))
        ref = float(pr.get("reference_price", 0) or 0)
        current = price_by_netuid.get(netuid, ref) or ref
        try:
            resolve_at = _dt.fromisoformat(pr.get("resolve_at", "").replace("Z", ""))
            remaining = resolve_at - now
            if remaining.total_seconds() > 0:
                hours, rem = divmod(int(remaining.total_seconds()), 3600)
                minutes = rem // 60
                time_remaining = f"{hours}h {minutes}m"
            else:
                time_remaining = "resolving"
        except Exception:
            time_remaining = "—"
        expert = pr.get("expert") or _expert_from_signal_source(pr.get("signal_source"))
        enriched = {
            **pr,
            "expert": expert,
            "current_estimate": round(current, 6),
            "time_remaining": time_remaining,
        }
        enriched_predictions.append(enriched)

    return {
        "simivision_picks": simivision_picks,
        "undervalued_radar": undervalued,
        "technical_indicators": technical_panel,
        "market_intelligence": market_intel,
        "staking_analytics": staking,
        "council_weights": council_weights,
        "expert_weights": expert_weights,
        "mindmap_trail": mindmap_trail,
        "signal_impact": signal_impacts,
        "patterns": patterns_all,
        "predictions": enriched_predictions,
        "learning_metrics": learning_metrics,
        "social_sentiment": social_feed,
        "indicators_convergence": {
            "oversold": _detect_oversold_convergence(_compute_technical_indicators(top_subnets[0])) if top_subnets else {},
            "overbought": _detect_overbought_convergence(_compute_technical_indicators(top_subnets[0])) if top_subnets else {},
        },
        "momentum_charts": momentum_charts,
        "judge_cards": judge_cards,
        "usd_rate": tao_usd,
    }



def _default_market_intelligence() -> Dict[str, Any]:
    return {
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


def _default_rotation_tracker() -> Dict[str, Any]:
    return {
        "patterns": [],
        "volatility_clusters": {"summary": {"mean_volatility": 0.0}},
    }


def _default_scenario_memory() -> Dict[str, Any]:
    return {
        "status": "ok",
        "scenarios": [],
        "regimes": {},
        "stats": {"total": 0, "by_regime": {}},
        "meta": {},
    }


def _default_learning_metrics() -> Dict[str, Any]:
    return {
        "expert_weights": {},
        "total_records": 0,
        "predictions_pending": 0,
        "predictions_resolved": 0,
        "correct": 0,
        "wrong": 0,
        "accuracy": 0.0,
        "deltas": {"correct": 0.02, "wrong": -0.03},
        "recent_resolutions": [],
        "last_updated": None,
    }


def _default_premium_context() -> Dict[str, Any]:
    """Return a fully populated premium context with safe defaults."""
    return {
        "simivision_picks": [],
        "undervalued_radar": [],
        "technical_indicators": [],
        "market_intelligence": _default_market_intelligence(),
        "staking_analytics": {
            "total_stake": 0.0,
            "avg_apy": 0.0,
            "subnet_count": 0,
            "top_yield": [],
        },
        "council_weights": [],
        "expert_weights": {},
        "mindmap_trail": [],
        "signal_impact": [],
        "patterns": [],
        "predictions": [],
        "learning_metrics": _default_learning_metrics(),
        "social_sentiment": [],
        "indicators_convergence": {"oversold": {}, "overbought": {}},
        "momentum_charts": {"treemap": [], "radar": {"labels": [], "datasets": []}},
        "judge_cards": [],
        "usd_rate": None,
        # Dashboard-specific keys referenced by templates/index.html. These are
        # included so the fallback render (which starts from this context) has
        # every top-level variable the template expects, avoiding
        # "UndefinedError" when the primary render fails.
        "hour_picks": [],
        "day_picks": [],
        "daily_pick": {},
        "rotation_tracker": _default_rotation_tracker(),
        "scenario_memory": _default_scenario_memory(),
        "api_indicators_convergence": {"subnets": []},
        "pump_analytics": _safe_pump_analytics(),
    }


# ---------------------------------------------------------------------------
# Scenario-memory wiring helpers for the homepage top-pick sections.
#
# The top picks previously showed static "Market Mood: neutral · rsi: neutral ·
# volume: low" because (a) the market mood was derived from a hardcoded
# tao_change_24h of 0.0, and (b) nothing attached the recorded scenario-memory
# regime/features/outcome to each pick. The helpers below derive a real
# market-wide mood, look up the latest recorded scenario per subnet, and build
# fallback picks from the top-conviction subnets when the pipeline is empty.
# ---------------------------------------------------------------------------

# Map the canonical scenario-memory regime buckets onto the display vocabulary
# used by the "Market Mood" scenario tag.
_REGIME_DISPLAY = {
    "bull": "bullish",
    "bear": "bearish",
    "volatile": "volatile",
    "neutral": "neutral",
}


def _market_mood_proxy(subnets: List[Dict[str, Any]]) -> float:
    """Return a market-wide 24h change proxy from the average subnet change.

    Used as ``tao_change_24h`` for the regime classifier so "Market Mood"
    reflects actual aggregate movement instead of a static 0.0.
    """
    changes = []
    for sn in subnets or []:
        try:
            chg = float(sn.get("price_change_24h", 0) or 0)
        except (TypeError, ValueError):
            continue
        changes.append(chg)
    if not changes:
        return 0.0
    return sum(changes) / len(changes)


def _latest_scenario_by_name(scenarios: Any) -> Dict[str, Dict[str, Any]]:
    """Index the most recent scenario per subnet name from a scenario list."""
    by_name: Dict[str, Dict[str, Any]] = {}
    if not isinstance(scenarios, list):
        return by_name
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        name = sc.get("name")
        if not name:
            continue
        # Scenarios are appended in time order, so the last one wins.
        by_name[str(name)] = sc
    return by_name


def _enrich_pick_scenario(
    pick: Dict[str, Any],
    scenarios_by_name: Dict[str, Dict[str, Any]],
) -> None:
    """Attach the latest recorded scenario (regime/features/outcome) to a pick.

    When a recorded scenario exists for the pick's subnet, its regime overrides
    the live "Market Mood" tag (mapped to the display vocabulary) and the
    scenario is exposed as ``pick["sc"]`` for templates that render
    ``sc.regime`` / ``sc.features`` / ``sc.outcome``. When no scenario has been
    recorded yet, the live indicator-derived ``scenario_tags`` (already computed
    by the scoring functions) are kept as the fallback.
    """
    if not isinstance(pick, dict):
        return
    name = pick.get("name")
    sc = scenarios_by_name.get(str(name)) if name else None
    if not isinstance(sc, dict):
        return
    pick["sc"] = {
        "regime": sc.get("regime"),
        "features": sc.get("features", {}),
        "outcome": sc.get("outcome"),
    }
    tags = pick.get("scenario_tags")
    if not isinstance(tags, dict):
        tags = {}
        pick["scenario_tags"] = tags
    recorded_regime = _REGIME_DISPLAY.get(str(sc.get("regime", "")).lower())
    if recorded_regime:
        tags["regime"] = recorded_regime
    # Surface recorded RSI/volume signals when present in the scenario features.
    features = sc.get("features", {})
    if isinstance(features, dict):
        if features.get("rsi"):
            tags["rsi"] = str(features["rsi"])
        if features.get("volume"):
            tags["volume"] = str(features["volume"])


def _conviction_proxy(sn: Dict[str, Any]) -> float:
    """A simple conviction proxy for ranking fallback picks.

    Combines emission (income), APY (yield) and absolute 24h momentum so the
    fallback surfaces subnets that are both rewarding and moving.
    """
    try:
        emission = float(sn.get("emission", 0) or 0)
    except (TypeError, ValueError):
        emission = 0.0
    try:
        apy = float(sn.get("apy", 0) or 0)
    except (TypeError, ValueError):
        apy = 0.0
    try:
        chg = abs(float(sn.get("price_change_24h", 0) or 0))
    except (TypeError, ValueError):
        chg = 0.0
    return emission + apy + chg


def _build_fallback_picks(
    subnets: List[Dict[str, Any]],
    market_context: Dict[str, Any],
    horizon: str,
) -> List[Dict[str, Any]]:
    """Build minimal top-3 picks from the highest-conviction subnets.

    Used when the primary scoring pipeline produced no picks. Each pick carries
    its current indicator-derived scenario tags (regime/rsi/volume) computed via
    the shared scoring functions, so the sections never render empty or
    all-defaults.
    """
    picks: List[Dict[str, Any]] = []
    try:
        ranked = sorted(subnets, key=_conviction_proxy, reverse=True)[:3]
        scorer = score_subnet_for_hour if horizon == "hour" else score_subnet_for_day
        for sn in ranked:
            try:
                score = scorer(sn, market_context)
            except Exception as exc:
                logger.warning("Fallback scorer failed for SN%s: %s", sn.get("netuid"), exc)
                continue
            picks.append({
                "netuid": sn.get("netuid"),
                "name": sn.get("name"),
                "symbol": sn.get("symbol"),
                "score": score.get("total_score", 0.0),
                "confidence": score.get("confidence", 0.0),
                "signals": {
                    "price_change_24h": sn.get("price_change_24h"),
                    "price_change_7d": sn.get("price_change_7d"),
                    "emission": sn.get("emission"),
                    "apy": sn.get("apy"),
                    "volume": sn.get("volume"),
                },
                "scenario_tags": score.get("scenario_tags", {}),
            })
    except Exception as exc:
        logger.error("Error building fallback %s picks: %s", horizon, exc)
    return picks


@router.get("/")
async def dashboard(request: Request):
    """Render the SimiVision dashboard server-side via Jinja2.

    Context flows: server fetches subnets + SimiVision picks + mindmap summary
    + learning stats -> renders into templates/index.html -> user sees the
    complete dashboard. Vanilla JS polls /api/subnets every 5 min for refresh.

    The route is hardened so that any partial failure still yields a renderable
    context: every template key is guaranteed, and per-section helpers fall back
    to safe defaults rather than aborting the whole page.
    """
    subnets: List[Dict[str, Any]] = []
    source = "unknown"
    premium = _default_premium_context()
    # Derive a real market-wide mood from the average subnet 24h change so the
    # "Market Mood" scenario tag reflects actual movement instead of a static
    # 0.0 (which always classified as "neutral"). Recomputed after subnets load.
    market_context = {"tao_change_24h": 0.0}
    hour_picks: List[Dict[str, Any]] = []
    day_picks: List[Dict[str, Any]] = []
    daily_pick: Dict[str, Any] = {}
    rotation_tracker: Dict[str, Any] = _default_rotation_tracker()
    scenario_memory_snapshot: Dict[str, Any] = _default_scenario_memory()
    indicators_convergence: Dict[str, Any] = {"subnets": []}
    render_error: Optional[str] = None

    try:
        subnets, source = _get_subnets_with_source()
        _mark_fresh("subnets")
    except Exception as e:
        logger.error("Error fetching subnets for dashboard: %s", e)
        subnets, source = [], "error"

    # Recompute the market mood now that we have real subnets.
    market_context = {"tao_change_24h": _market_mood_proxy(subnets)}

    try:
        premium = _build_premium_context(subnets)
        # The premium context composes simivision picks, technical indicators,
        # predictions, social sentiment, and judge cards in one pass.
        _mark_fresh("simivision_picks")
        _mark_fresh("indicators")
        _mark_fresh("predictions")
        _mark_fresh("social_sentiment")
        _mark_fresh("judges")
    except Exception as e:
        logger.error("Error building premium context: %s", e)
        premium = _default_premium_context()

    try:
        # Use the SAME shared helper as /api/top-pick/hour so the homepage #1
        # pick always matches the highest-scored (audited) pick from the API.
        # The helper returns a unified shape carrying both top-level
        # name/netuid/score/confidence/signals/scenario_tags (template) and
        # nested subnet{}/action (API), and records each pick into the
        # regime-aware scenario memory.
        hour_picks = _ordered_hour_picks(subnets, market_context, limit=3)
        _mark_fresh("top_pick_hour")
    except Exception as e:
        logger.error("Error computing hour picks: %s", e)
        hour_picks = []

    try:
        _dp_raw = get_or_create_today_pick(subnets, market_context)
        daily_pick_result = _dp_raw.get("pick") if isinstance(_dp_raw, dict) and _dp_raw.get("pick") else _dp_raw
        if daily_pick_result and daily_pick_result.get("subnet"):
            candidate = daily_pick_result["subnet"]
            sn = next(
                (s for s in subnets if s.get("netuid") == candidate.get("netuid")),
                {},
            )
            _day_pick = {
                "netuid": candidate.get("netuid"),
                "name": candidate.get("name"),
                "symbol": candidate.get("symbol"),
                "score": daily_pick_result.get("score", 0.0),
                "confidence": daily_pick_result.get("confidence", 0.0),
                "signals": {
                    "price_change_24h": sn.get("price_change_24h"),
                    "price_change_7d": sn.get("price_change_7d"),
                    "emission": sn.get("emission"),
                    "apy": sn.get("apy"),
                    "volume": sn.get("volume"),
                },
                "scenario_tags": daily_pick_result.get("scenario_tags", {}),
            }
            day_picks.append(_day_pick)
            # Record the day pick's market context into the scenario memory.
            _record_pick_scenario(_day_pick, market_context)
            _mark_fresh("top_pick_day")
    except Exception as e:
        logger.error("Error computing day picks: %s", e)
        day_picks = []

    # Live Council State Vector fallback: never render an empty council. If the
    # backend computation returned no picks but subnets exist, fall back to the
    # highest-ranked subnet so the homepage always shows a state vector.
    if not hour_picks and subnets:
        hour_picks = [_fallback_state_pick(subnets)]
    if not day_picks and subnets:
        day_picks = [_fallback_state_pick(subnets)]

    try:
        # Use the Council engine directly so the homepage shows the audited,
        # persisted daily pick. ``get_or_create_today_pick`` returns the engine
        # payload whose ``pick`` key holds the actual pick data
        # (subnet/action/final_confidence/confidence/audit/scenario_tags) that
        # templates/index.html renders as ``daily_pick.*``.
        daily_pick_result = get_or_create_today_pick(subnets, market_context)
        daily_pick = daily_pick_result.get("pick") if isinstance(daily_pick_result, dict) else None
        if not isinstance(daily_pick, dict):
            daily_pick = {}
    except Exception as e:
        logger.error("Error fetching daily pick: %s", e)
        daily_pick = {}

    try:
        rotation_tracker = await api_rotation_tracker()
        _mark_fresh("rotation")
    except Exception as e:
        logger.error("Error fetching rotation tracker: %s", e)
        rotation_tracker = _default_rotation_tracker()

    try:
        scenario_memory_snapshot = await api_scenario_memory()
        _mark_fresh("scenario_memory")
    except Exception as e:
        logger.error("Error fetching scenario memory: %s", e)
        scenario_memory_snapshot = _default_scenario_memory()

    # Enrich each pick with the latest recorded scenario for its subnet
    # (regime, features, outcome) and let the recorded regime override the live
    # "Market Mood" tag when available. Falls back to the live indicator-derived
    # tags (already computed above) when no scenario has been recorded yet.
    scenarios_by_name = _latest_scenario_by_name(
        scenario_memory_snapshot.get("scenarios", [])
    )
    for pick in hour_picks:
        _enrich_pick_scenario(pick, scenarios_by_name)
    for pick in day_picks:
        _enrich_pick_scenario(pick, scenarios_by_name)

    # Fallback: if the picks pipeline produced nothing (e.g. scoring failed but
    # subnets are available), pull the top subnets by conviction and build
    # minimal pick objects carrying their current indicator-derived scenario
    # tags so the sections never render empty or all-defaults.
    if not hour_picks and subnets:
        hour_picks = _build_fallback_picks(subnets, market_context, "hour")
    if not day_picks and subnets:
        day_picks = _build_fallback_picks(subnets, market_context, "day")

    try:
        indicators_convergence = await api_indicators_convergence()
    except Exception as e:
        logger.error("Error fetching indicators convergence: %s", e)
        indicators_convergence = {"subnets": []}

    context = {
        "subnets": subnets,
        "data_source": source,
        "mindmap": get_mindmap_summary(),
        "learning_stats": get_learning_stats(),
        "simivision": get_simivision_data(),
        "rotation_tokens": _ROTATION_TOKENS,
        "simivision_picks": premium.get("simivision_picks", []),
        "undervalued_radar": premium.get("undervalued_radar", []),
        "technical_indicators": premium.get("technical_indicators", []),
        "market_intelligence": premium.get("market_intelligence", _default_market_intelligence()),
        "staking_analytics": premium.get("staking_analytics", {
            "total_stake": 0.0,
            "avg_apy": 0.0,
            "subnet_count": 0,
            "top_yield": [],
        }),
        "council_weights": premium.get("council_weights", []),
        "expert_weights": premium.get("expert_weights", {}),
        "mindmap_trail": premium.get("mindmap_trail", []),
        "signal_impact": premium.get("signal_impact", []),
        "patterns": premium.get("patterns", []),
        "predictions": premium.get("predictions", []),
        "learning_metrics": premium.get("learning_metrics", _default_learning_metrics()),
        "social_sentiment": premium.get("social_sentiment", []),
        "indicators_convergence": premium.get("indicators_convergence", {"oversold": {}, "overbought": {}}),
        "momentum_charts": premium.get("momentum_charts", {"treemap": [], "radar": {"labels": [], "datasets": []}}),
        "judge_cards": premium.get("judge_cards", []),
        "usd_rate": premium.get("usd_rate"),
        "hour_picks": hour_picks,
        "day_picks": day_picks,
        "daily_pick": daily_pick,
        "rotation_tracker": rotation_tracker,
        "scenario_memory": scenario_memory_snapshot,
        "api_indicators_convergence": indicators_convergence,
        "pump_analytics": _safe_pump_analytics(),
    }

    try:
        context["request"] = request
        return templates.TemplateResponse("index.html", context)
    except Exception as e:
        logger.error("Error rendering dashboard template: %s\n%s", e, traceback.format_exc())
        render_error = str(e)
        # Minimal fallback response so the page still loads with defaults.
        # Do NOT reuse the original context values that may have caused the
        # render failure; start from safe defaults and only keep known-safe
        # scalar metadata.
        fallback_context = _default_premium_context()
        fallback_context["request"] = request
        fallback_context["render_error"] = render_error
        fallback_context["data_source"] = source
        fallback_context["subnets"] = subnets if isinstance(subnets, list) else []
        try:
            return templates.TemplateResponse("index.html", fallback_context)
        except Exception as e2:
            logger.error("Fallback dashboard render also failed: %s\n%s", e2, traceback.format_exc())
            return PlainTextResponse(
                f"RENDER ERROR: {render_error}\n\nFALLBACK ERROR: {e2}\n\nFULL TRACEBACK:\n{traceback.format_exc()}",
                status_code=500,
            )


@router.get("/api/predictions")
async def api_predictions():
    """Return pending + resolved predictions from the predictive engine.

    All entries use the predictive framing: 'predicted to move +X% within N hours'.
    Resolved entries carry actual_pct + correctness for the learning loop.
    """
    try:
        data = PREDICTION_STORE._load()
        PREDICTION_STORE.update_stats(data)
        PREDICTION_STORE._save(data)
        return {
            "predictions": data.get("predictions", []),
            "resolved": data.get("resolved", []),
            "stats": data.get("stats", {}),
        }
    except Exception as e:
        logger.error("Error fetching predictions: %s", e)
        return {"predictions": [], "resolved": [], "stats": {}, "error": str(e)}


@router.get("/api/predictions/resolved")
async def api_predictions_resolved(resolve: bool = False):
    """Return resolved predictions. Trigger a 24h resolution pass when ``resolve=1``."""
    try:
        if resolve:
            subnets, _ = _get_subnets_with_source()
            result = resolver.resolve_due_predictions(subnets)
        else:
            result = resolver.get_resolved_predictions()
        return {
            "status": "ok",
            "resolved": result.get("resolved", []),
            "stats": result.get("stats", {}),
            "triggered_resolution": resolve,
        }
    except Exception as e:
        logger.error("Error resolving predictions: %s", e)
        return {"status": "error", "resolved": [], "stats": {}, "error": str(e)}


@router.get("/api/scenario-memory")
async def api_scenario_memory():
    """Return the full regime-aware scenario memory snapshot."""
    try:
        _mark_fresh("scenario_memory")
        return {"status": "ok", **scenario_memory.get_memory_snapshot()}
    except Exception as e:
        logger.error("Error fetching scenario memory: %s", e)
        return {"status": "error", "scenarios": [], "regimes": {}, "stats": {}, "meta": {}, "error": str(e)}


@router.post("/api/scenario-memory")
async def api_scenario_memory_add(request: Request):
    """Record a new regime-aware scenario into persistent memory."""
    try:
        payload = await request.json()
    except Exception as e:
        return {"status": "error", "error": f"Invalid JSON body: {e}"}

    name = payload.get("name")
    features = payload.get("features", {})
    if not name or not isinstance(features, dict):
        return {"status": "error", "error": "Missing 'name' or 'features'"}

    try:
        scenario = scenario_memory.add_scenario(
            name=name,
            features=features,
            outcome=payload.get("outcome"),
            regime=payload.get("regime"),
            metadata=payload.get("metadata"),
        )
        return {"status": "ok", "scenario": scenario}
    except Exception as e:
        logger.error("Error adding scenario: %s", e)
        return {"status": "error", "error": str(e)}


@router.get("/api/rotation-tracker")
async def api_rotation_tracker():
    """Return subnet rotation patterns and volatility clusters."""
    try:
        subnets, _ = _get_subnets_with_source()
        _mark_fresh("rotation")
        return {"status": "ok", **rotation_tracker.get_rotation_summary(subnets)}
    except Exception as e:
        logger.error("Error fetching rotation tracker: %s", e)
        return {"status": "error", "patterns": [], "volatility_clusters": {}, "error": str(e)}


@router.get("/api/learning-metrics")
async def api_learning_metrics():
    """Return learning-loop metrics: expert weights, accuracy, recent resolutions."""
    try:
        return _compute_learning_metrics()
    except Exception as e:
        logger.error("Error fetching learning metrics: %s", e)
        return {"error": str(e), "expert_weights": {}, "accuracy": 0.0}


@router.get("/api/indicators-convergence")
async def api_indicators_convergence():
    """Return multi-indicator oversold/overbought convergence for top subnets."""
    try:
        subnets, _ = _get_subnets_with_source()
        ranked = sorted(subnets, key=lambda s: (s.get("emission", 0), s.get("apy", 0), s.get("volume", 0)), reverse=True)
        rows = []
        for sn in ranked[:6]:
            indicators = _compute_technical_indicators(sn)
            rows.append({
                "netuid": sn.get("netuid"),
                "name": sn.get("name"),
                "oversold": _detect_oversold_convergence(indicators),
                "overbought": _detect_overbought_convergence(indicators),
            })
        _mark_fresh("indicators")
        return {"subnets": rows}
    except Exception as e:
        logger.error("Error fetching indicators convergence: %s", e)
        return {"subnets": [], "error": str(e)}


@router.get("/api/indicators")
async def api_indicators():
    """Return the latest technical-indicator state from the indicator engine."""
    try:
        return {
            "status": "success",
            "data": IndicatorEngine().get_indicator_state(),
        }
    except Exception as e:
        logger.error("Error fetching indicator state: %s", e)
        return {"status": "error", "data": {}, "error": str(e)}


@router.get("/api/top-picks")
async def api_top_picks():
    """Return top 3 subnets by short-horizon and 24h Council state-vector scores."""
    try:
        subnets, _ = _get_subnets_with_source()
        # Use the same real market-wide mood proxy as the homepage so the
        # short-horizon / day scores here match the audited picks everywhere.
        market_context = {"tao_change_24h": _market_mood_proxy(subnets)}

        hour_scored = []
        day_scored = []
        for sn in subnets:
            hour = score_subnet_for_hour(sn, market_context)
            day = score_subnet_for_day(sn, market_context)
            hour_scored.append({"subnet": sn, "score": hour})
            day_scored.append({"subnet": sn, "score": day})

        hour_scored.sort(key=lambda x: x["score"]["total_score"], reverse=True)
        day_scored.sort(key=lambda x: x["score"]["total_score"], reverse=True)

        def _format(item):
            sn = item["subnet"]
            sc = item["score"]
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
    except Exception as e:
        logger.error("Error fetching top picks: %s", e)
        return {"hour_picks": [], "day_picks": [], "error": str(e)}


def _record_pick_scenario(pick: Dict[str, Any], market_context: Optional[Dict[str, Any]] = None) -> None:
    """Record a pick's market context into the regime-aware scenario memory.

    Called at pick-generation time (both the hourly API and the homepage) so
    ``/api/scenario-memory`` reflects real picks instead of staying empty
    until a prediction is resolved. A per-name 1-hour dedup window prevents
    the homepage refresh loop from flooding the memory with near-duplicate
    entries. Failures are swallowed so a memory-store hiccup can never break
    pick generation.
    """
    try:
        name = pick.get("name")
        if not name:
            return
        signals = pick.get("signals") if isinstance(pick.get("signals"), dict) else {}
        tags = pick.get("scenario_tags") if isinstance(pick.get("scenario_tags"), dict) else {}
        chg = float(signals.get("price_change_24h", 0) or 0)
        features = {
            "avg_change_24h": chg,
            "price_change_24h": chg,
            "volatility": abs(chg),
            "score": float(pick.get("score", 0) or 0),
            "confidence": float(pick.get("confidence", 0) or 0),
            "rsi": tags.get("rsi"),
            "volume": signals.get("volume") or tags.get("volume"),
            "daily_rewards": signals.get("emission"),
            "apy": signals.get("apy"),
            "market_mood": (market_context or {}).get("tao_change_24h", 0),
        }
        # Dedup: skip if a scenario for this subnet was recorded in the last hour.
        now = _dt.utcnow()
        cutoff = now - _td(hours=1)
        for existing in scenario_memory.get_scenarios():
            if existing.get("name") != name:
                continue
            try:
                created = _dt.fromisoformat(str(existing.get("created_at", "")).replace("Z", ""))
            except Exception:
                continue
            if created >= cutoff:
                return  # already recorded this subnet recently
        scenario_memory.add_scenario(
            name=str(name),
            features=features,
            regime=scenario_memory.classify_regime(features),
        )
    except Exception as exc:
        logger.warning("scenario memory record failed for %s: %s", pick.get("name"), exc)


def _ordered_hour_picks(
    subnets: List[Dict[str, Any]],
    market_context: Dict[str, Any],
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """Build the canonical ordered hourly picks used by BOTH the API and the
    homepage so the two never diverge.

    The #1 pick is the RedTeam-audited hourly pick from ``select_hourly_pick``
    (which runs ``score_subnet_for_hour`` + the audit/tie-break layer);
    remaining slots are filled from raw hourly scoring, excluding the #1
    netuid, sorted by ``total_score`` desc.

    Each returned pick carries a UNIFIED shape: top-level ``name``/``netuid``/
    ``symbol``/``score``/``confidence``/``scenario_tags``/``signals`` (for the
    homepage template) AND nested ``subnet{}``/``action``/``expert_contributions``
    (for the ``/api/top-pick/hour`` response). Every pick is also recorded into
    the scenario memory via ``_record_pick_scenario``.
    """
    picks: List[Dict[str, Any]] = []
    if not subnets:
        return picks

    try:
        audited = select_hourly_pick(subnets, market_context)
    except Exception as exc:
        logger.warning("select_hourly_pick failed: %s", exc)
        audited = None
    if not audited:
        audited = _highest_emission_pick(subnets)

    top_netuid = None
    if isinstance(audited, dict) and isinstance(audited.get("subnet"), dict):
        top_netuid = audited["subnet"].get("netuid")
        # Graft the raw market signals the audited payload lacks.
        if "signals" not in audited:
            src = next((s for s in subnets if s.get("netuid") == top_netuid), {})
            audited["signals"] = {
                "price_change_24h": src.get("price_change_24h"),
                "price_change_7d": src.get("price_change_7d"),
                "emission": src.get("emission"),
                "apy": src.get("apy"),
                "volume": src.get("volume"),
            }

    def _unify(payload: Dict[str, Any], sn: Dict[str, Any]) -> Dict[str, Any]:
        """Merge API shape (subnet{}/action) with template shape (top-level)."""
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

    if audited:
        src = next((s for s in subnets if s.get("netuid") == top_netuid), {})
        picks.append(_unify(audited, src))

    scored: List[Dict[str, Any]] = []
    for sn in subnets:
        if top_netuid is not None and sn.get("netuid") == top_netuid:
            continue
        try:
            score = score_subnet_for_hour(sn, market_context)
        except Exception as exc:
            logger.warning("score_subnet_for_hour failed for SN%s: %s", sn.get("netuid"), exc)
            continue
        scored.append({"subnet": sn, "score": score})
    scored.sort(key=lambda x: x["score"]["total_score"], reverse=True)
    for item in scored[: max(0, limit - len(picks))]:
        picks.append(_unify(_build_hour_pick_payload(item["subnet"], item["score"]), item["subnet"]))

    # Record each pick's market context into the regime-aware scenario memory.
    for pick in picks:
        _record_pick_scenario(pick, market_context)

    # Track the #1 Pick of the Hour for the entry-price + success-metric
    # feature (Stream C). This records selected_at/entry_price/trigger_reason
    # on first sight of a new #1 netuid and finalizes the previous pick's
    # outcome (absolute vs median subnet return) when the #1 changes. The
    # enriched fields are merged back onto the #1 pick so both the homepage
    # and /api/top-pick/hour surface them. Idempotent for the same netuid.
    if picks:
        try:
            top_sn = next((s for s in subnets if s.get("netuid") == picks[0].get("netuid")), {})
            top_ind = _compute_technical_indicators(top_sn) if top_sn else None
            picks[0] = _record_hour_pick(picks[0], subnets, top_ind)
        except Exception as exc:
            logger.warning("hour pick history tracking failed: %s", exc)

    return picks[:limit]


def _build_hour_pick_payload(sn: Dict[str, Any], score: Dict[str, Any]) -> Dict[str, Any]:
    """Format a subnet + hour state-vector into the public hour-pick shape."""
    return {
        "subnet": {
            "netuid": sn.get("netuid"),
            "name": sn.get("name"),
            "symbol": sn.get("symbol"),
        },
        "score": score["total_score"],
        "confidence": score["confidence"],
        "expert_contributions": score["expert_contributions"],
        "scenario_tags": score["scenario_tags"],
        "signals": {
            "price_change_24h": sn.get("price_change_24h"),
            "price_change_7d": sn.get("price_change_7d"),
            "emission": sn.get("emission"),
            "apy": sn.get("apy"),
            "volume": sn.get("volume"),
        },
        "action": "long",
    }


@router.get("/api/top-pick/hour")
async def api_top_pick_hour():
    """Return the top short-horizon picks with a safe fallback.

    Uses the shared ``_ordered_hour_picks`` helper so the #1 pick is identical
    to what the homepage renders (RedTeam-audited hourly pick first, then raw
    score-ranked fill). This guarantees the API and homepage never diverge.
    """
    try:
        subnets, _ = _get_subnets_with_source()
        # Use the SAME real market-wide mood proxy as the homepage so the
        # audited #1 pick is byte-for-byte identical between the API and the
        # rendered dashboard (a static 0.0 here previously let the two drift).
        market_context = {"tao_change_24h": _market_mood_proxy(subnets)}
        picks = _ordered_hour_picks(subnets, market_context, limit=3)
        _mark_fresh("top_pick_hour")
        if picks:
            return {"picks": picks}
        return {"picks": [_highest_emission_pick(subnets)]}
    except Exception as e:
        logger.error("Error fetching hour pick: %s", e)
        subnets, _ = _get_subnets_with_source()
        return {"picks": [_highest_emission_pick(subnets)]}


