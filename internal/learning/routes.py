
    try:
        return await _to_thread_timeout(
            lambda: build_story_strip(limit=limit, focus_netuid=focus),
            STORY_STRIP_HANDLER_TIMEOUT,
            label="story-strip",
        )
    except asyncio.TimeoutError:
        return {
            "data_available": False,
            "reason": "timeout",
            "items": [],
            "stats": {"correct": 0, "wrong": 0},
        }


@learning_router.get("/api/mindmap/story-path")
async def api_mindmap_story_path():
    """§21 L5 — linear cause chain for today's council pick."""
    try:
        return await _to_thread_timeout(
            _build_mindmap_story_path,
            MINDMAP_STORY_PATH_HANDLER_TIMEOUT,
            label="mindmap-story-path",
        )
    except asyncio.TimeoutError:
        stale = _get_stale_story_path()
        if stale:
            out = dict(stale)
            out["status"] = "cached"
            return out
        return {
            "status": "timeout",
            "data_available": False,
            "reason": "timeout",
            "steps": [],
        }
    except Exception as exc:
        logger.warning("mindmap story-path failed: %s", exc)
        return {
            "status": "error",
            "data_available": False,
            "reason": "error",
            "steps": [],
            "error": str(exc),
        }


def _load_today_pick_payload_lite() -> Dict[str, Any]:
    """File-backed daily pick — no live subnet-universe scoring."""
    from internal.council.daily_pick_engine import _find_today, _load

    daily = _find_today(_load())
    return daily if isinstance(daily, dict) else {}


def _get_stale_story_path() -> Dict[str, Any] | None:
    cached = _STORY_PATH_CACHE.get("payload")
    if isinstance(cached, dict):
        return dict(cached)
    return None


def _build_mindmap_story_path() -> Dict[str, Any]:
    now = time.monotonic()
    cached = _STORY_PATH_CACHE.get("payload")
    if isinstance(cached, dict) and now - float(_STORY_PATH_CACHE.get("at") or 0) < _STORY_PATH_CACHE_TTL:
        return dict(cached)

    from internal.learning.story_path import build_story_path

    payload = _load_today_pick_payload_lite()
    out = {"status": "success", **build_story_path(payload)}
    _STORY_PATH_CACHE["at"] = now
    _STORY_PATH_CACHE["payload"] = out
    return out


@learning_router.get("/api/predictions/capsule/{prediction_id}")
async def api_prediction_capsule(prediction_id: str):
    """§21 L12 — time-capsule replay for a graded call."""
    try:
        from internal.learning.prediction_capsule import get_prediction_capsule

        return get_prediction_capsule(prediction_id)
    except Exception as exc:
        logger.warning("prediction capsule failed: %s", exc)
        return {"status": "error", "reason": str(exc)}


@learning_router.get("/api/predictions/capsule/{prediction_id}/og.svg")
async def api_prediction_capsule_og(prediction_id: str):
    """§22 S22-3 — OG share card image for a graded call."""
    from internal.learning.prediction_capsule import build_og_svg, get_prediction_capsule

    data = get_prediction_capsule(prediction_id)
    if data.get("status") != "success":
        svg = build_og_svg(
            {
                "name": "Graded call",
                "correct": None,
                "statement": "Prediction not found or not yet graded.",
            }
        )
    else:
        svg = build_og_svg(data.get("prediction") or {})
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=300"},
    )


@learning_router.get("/api/predictions/capsule/{prediction_id}/og.png")
async def api_prediction_capsule_og_png(prediction_id: str):
    """§23 S23-1 — OG share card PNG for social crawlers."""
    from internal.learning.prediction_capsule import build_og_png, get_prediction_capsule

    data = get_prediction_capsule(prediction_id)
    if data.get("status") != "success":
        png = build_og_png(
            {
                "name": "Graded call",
                "correct": None,
                "statement": "Prediction not found or not yet graded.",
            }
        )
    else:
        png = build_og_png(data.get("prediction") or {})
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )


@learning_router.get("/share/call/{prediction_id}", response_class=HTMLResponse)
async def share_call_page(prediction_id: str, request: Request):
    """§22 S22-3 — public share page with OG meta for social crawlers."""
    from internal.learning.prediction_capsule import capsule_share_urls, get_prediction_capsule

    data = get_prediction_capsule(prediction_id)
    if data.get("status") != "success":
        return HTMLResponse(
            """<!DOCTYPE html><html><head><title>Graded call not found</title>
            <meta name="robots" content="noindex"></head>
            <body><p>Prediction not found.</p><p><a href="/">Open SimiVision</a></p></body></html>"""
        )

    pred = data.get("prediction") or {}
    name = pred.get("name") or f"SN{pred.get('netuid', '?')}"
    urls = capsule_share_urls(prediction_id)
    base = os.environ.get("APP_BASE_URL", "").strip().rstrip("/") or str(request.base_url).rstrip("/")
    image_url = f"{base}{urls['share_image_png_url']}"
    page_url = f"{base}{urls['share_page_url']}"
    title = f"SimiVision graded call — {name}"
    desc = (pred.get("statement") or "Direction-graded subnet call from the SimiVision learning loop.")[:200]
    esc = html.escape

    return HTMLResponse(
        f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(desc)}">
  <meta property="og:type" content="article">
  <meta property="og:url" content="{esc(page_url)}">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(desc)}">
  <meta property="og:image" content="{esc(image_url)}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{esc(title)}">
  <meta name="twitter:description" content="{esc(desc)}">
  <meta name="twitter:image" content="{esc(image_url)}">
</head>
<body style="margin:0;background:#0a0a0a;color:#e8f0e9;font-family:system-ui,sans-serif;">
  <main style="max-width:720px;margin:0 auto;padding:24px;text-align:center;">
    <img src="{esc(urls['share_image_png_url'])}" alt="{esc(title)}" style="max-width:100%;height:auto;border-radius:12px;">
    <p style="margin-top:16px;color:#8a9a8e;">{esc(desc)}</p>
    <p><a href="/" style="color:#00ff41;">Open SimiVision Council</a></p>
  </main>
</body>
</html>"""
    )


@learning_router.get("/api/learning/health")
async def api_learning_loop_health():
    """Phase 0 — pick→ledger→resolver loop status (no scoring)."""
    cached = _get_cached_learning_health()
    if cached is not None:
        from internal.ops.bot_policy import with_bot_contract

        return {
            **cached,
            **with_bot_contract(
                {},
                source="learning_health",
                captured_at=cached.get("checked_at"),
                degraded=cached.get("status") == "degraded",
            ),
        }
    if _learning_health_build_in_flight():
        stale = _get_cached_learning_health(allow_stale=True)
        return _stale_learning_health(stale) if stale is not None else _learning_health_degraded(source="refreshing")

    try:
        payload = await _to_thread_timeout(
            _build_learning_health_once, LEARNING_HEALTH_TIMEOUT, label="learning-health"
        )
        if payload is None:
            stale = _get_cached_learning_health(allow_stale=True)
            return _stale_learning_health(stale) if stale is not None else _learning_health_degraded(source="refreshing")
        if _valid_learning_health(payload):
            _set_learning_health_cache(payload)
            from internal.ops.bot_policy import with_bot_contract

            return {
                **payload,
                **with_bot_contract(
                    {},
                    source="learning_health",
                    captured_at=payload.get("checked_at"),
                    degraded=payload.get("status") == "degraded",
                ),
            }
        logger.warning("learning health returned malformed payload")
        return _learning_health_degraded(source="invalid_payload", error="invalid_payload")
    except asyncio.TimeoutError:
        stale = _get_cached_learning_health(allow_stale=True)
        if stale is not None:
            return _stale_learning_health(stale)
        _schedule_learning_health_refresh()
        return _learning_health_degraded(source="timeout")
    except Exception as exc:
        logger.warning("learning health failed: %s", exc)
        return _learning_health_degraded(source="error", error="health_probe_failed")


@learning_router.get("/api/learning/stats")
async def api_learning_stats():
    try:
        snap = await _to_thread_timeout(
            _learning_snapshot, LEARNING_STATS_TIMEOUT, label="learning-stats"
        )
        payload = _learning_stats_payload(snap)
        from internal.ops.bot_policy import with_bot_contract

        return {
            **payload,
            **with_bot_contract(
                {},
                source="learning_outcomes",
                captured_at=(payload.get("data") or {}).get("last_updated"),
            ),
        }
    except asyncio.TimeoutError:
        return _learning_stats_degraded(source="timeout")
    except Exception as exc:
        logger.warning("learning stats failed: %s", exc)
        return _learning_stats_degraded(source="error")


@learning_router.post("/api/learning/rebalance-weights")
@limit_or_noop(strict_limit(), override_defaults=True)
async def api_learning_rebalance_weights(
    request: Request,
    replay_share: float = Query(default=0.7, ge=0.0, le=1.0),
    dry_run: bool = Query(default=False),
):
    """Slice R — replay council weights from ledger with re-attribution + soft reset."""
    from internal.council.weights import rebalance_council_weights

    try:
        result = rebalance_council_weights(replay_share=replay_share, save=not dry_run)
        _learning_snapshot_cache["at"] = 0.0
        return {"status": "success", "data": result}
    except Exception as exc:
        logger.error("rebalance-weights failed: %s", exc)
        raise HTTPException(status_code=500, detail=public_error(exc, code="rebalance_failed")["error"]) from exc


@learning_router.post("/api/learning/backfill-expert-attribution")
@limit_or_noop(strict_limit(), override_defaults=True)
async def api_backfill_expert_attribution(
    request: Request,
    dry_run: bool = Query(default=True),
):
    """Re-stamp council expert labels on ledger rows (dry_run default true; expert fields only)."""
    from internal.learning.expert_backfill import backfill_expert_attribution

    try:
        result = await run_in_threadpool(backfill_expert_attribution, dry_run=bool(dry_run))
        if not dry_run:
            _learning_snapshot_cache["at"] = 0.0
        return {"status": "success", "data": result}
    except Exception as exc:
        logger.error("backfill-expert-attribution failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=public_error(exc, code="expert_backfill_failed")["error"],
        ) from exc


@learning_router.get("/api/learning-metrics")
async def api_learning_metrics():
    try:
        snap = await _to_thread_timeout(
            _learning_snapshot, LEARNING_STATS_TIMEOUT, label="learning-metrics"
        )
        return _compute_learning_metrics(snap)
    except asyncio.TimeoutError:
        degraded = _learning_stats_degraded(source="timeout")
        return {
            "error": "timeout",
            "expert_weights": degraded["data"].get("expert_weights", {}),
            "accuracy": degraded["data"].get("accuracy", 0.0),
            "trust_banner": degraded["data"].get("trust_banner"),
        }


@learning_router.get("/api/predictions")
async def api_predictions():
    try:
        from internal.subnet_names import refresh_stored_names

        data = load_predictions()
        predictions = refresh_stored_names(data.get("predictions", []))
        resolved = refresh_stored_names(data.get("resolved", []))
        stats = resolver._compute_stats(data)
        return {
            "predictions": predictions,
            "resolved": resolved,
            "stats": stats,
        }
    except Exception as exc:
        logger.error("Error fetching predictions: %s", exc)
        return {"predictions": [], "resolved": [], "stats": {}, "error": str(exc)}


@learning_router.get("/api/predictions/resolved")
async def api_predictions_resolved(resolve: bool = Query(default=False)):
    """Return resolved predictions. Read-only unless ``resolve=true``."""
    try:
        if resolve:
            from internal.subnets.feed import load_pick_subnets

            subnets = load_pick_subnets()
            result = resolver.resolve_due_predictions(subnets)
        else:
            result = resolver.get_resolved_predictions()
        return {
            "status": "ok",
            "resolved": result.get("resolved", []),
            "stats": result.get("stats", {}),
            "triggered_resolution": resolve,
        }
    except Exception as exc:
        logger.error("Error resolving predictions: %s", exc)
        return {"status": "error", "resolved": [], "stats": {}, "error": str(exc)}


def _resolver_state_cross_process() -> Dict[str, Any]:
    """Resolver truth for the web process — the scheduler lives on the worker.

    In prod the web process serves HTTP only (``BACKGROUND_ON_WEB=off``), so its
    in-memory scheduler singleton is never started and reports ``running=false``
    / ``last_run_at=null`` even while the inline worker is ticking normally.
    The shared volume holds the real evidence: the resolver's cycle summary in
    the soul map plus the worker heartbeat.
    """
    from internal.run_mode import worker_mode_label

    state = dict(get_prediction_resolver_scheduler_state())
    state["in_process"] = {
        "running": state.get("running"),
        "last_run_at": state.get("last_run_at"),
    }
    try:
        from internal.learning.loop_health import _last_resolver_tick
    except Exception:
        state["source"] = "memory"
        return state

    persistence_started = time.perf_counter()
    try:
        tick = _last_resolver_tick()
    except Exception as exc:
        logger.warning("resolver cross-process state failed: %s", exc)
        state["source"] = "memory"
        return state
    finally:
        persistence_ms = (time.perf_counter() - persistence_started) * 1000
        logger.info(
            "resolver state stage=persistence duration_ms=%.1f",
            persistence_ms,
        )

    peer = tick.get("worker_peer") if isinstance(tick.get("worker_peer"), dict) else {}
    state["running"] = bool(tick.get("running"))
    if tick.get("at"):
        state["last_run_at"] = tick.get("at")
        state["last_run_ok"] = tick.get("ok")
    state["refresh_minutes"] = tick.get("refresh_minutes") or state.get("refresh_minutes")
    state["worker_peer"] = peer
    state["run_mode"] = worker_mode_label()
    state["source"] = "volume" if tick.get("at") else "memory"
    cycle = {}
    try:
        from internal.store.soul_map_io import read_soul_map

        persisted = read_soul_map()
        scheduler = persisted.get("prediction_resolver_scheduler", {})
        if isinstance(scheduler, dict):
            cycle = scheduler.get("last_cycle", {})
            if not isinstance(cycle, dict):
                cycle = {}
    except Exception:
        cycle = {}
    state["stage_timing_ms"] = dict(
        cycle.get("stage_timing_ms") or tick.get("stage_timing_ms") or {}
    )
    state["stage_timing_ms"]["persistence"] = persistence_ms
    state["active_stage"] = cycle.get("active_stage", tick.get("active_stage"))
    state["abandoned_live"] = cycle.get(
        "abandoned_live", tick.get("abandoned_live", 0)
    )
    return state


def _get_cached_resolver_state(*, allow_stale: bool = False) -> Optional[Dict[str, Any]]:
    now = time.monotonic()
    ttl = float("inf") if allow_stale else 5.0
    with _RESOLVER_STATE_CACHE_LOCK:
        payload = _RESOLVER_STATE_CACHE.get("payload")
        captured = float(_RESOLVER_STATE_CACHE.get("at") or 0.0)
        if isinstance(payload, dict) and now - captured <= ttl:
            return dict(payload)
    return None


def _set_cached_resolver_state(payload: Dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        return
    with _RESOLVER_STATE_CACHE_LOCK:
        _RESOLVER_STATE_CACHE["at"] = time.monotonic()
        _RESOLVER_STATE_CACHE["payload"] = dict(payload)


def _resolver_state_snapshot() -> Dict[str, Any]:
    """Build one resolver response snapshot and coalesce concurrent builders."""
    global _RESOLVER_STATE_BUILDING
    cached = _get_cached_resolver_state()
    if cached is not None:
        return cached
    with _RESOLVER_STATE_CACHE_LOCK:
        if _RESOLVER_STATE_BUILDING:
            stale = _RESOLVER_STATE_CACHE.get("payload")
            if isinstance(stale, dict):
                return dict(stale)
            logger.warning(
                "resolver state unavailable=true error=refresh_in_flight "
                "stage_persistence_ms=unknown stage_peer_access_ms=unknown "
                "stage_executor_wait_ms=0.0"
            )
            return {
                **get_prediction_resolver_scheduler_state(),
                "source": "memory",
                "availability": "unavailable",
                "unavailable_reason": "refresh_in_flight",
            }
        _RESOLVER_STATE_BUILDING = True
    try:
        data = _resolver_state_cross_process()
        _set_cached_resolver_state(data)
        return data
    finally:
        with _RESOLVER_STATE_CACHE_LOCK:
            _RESOLVER_STATE_BUILDING = False


def _resolver_timestamp_age_seconds(value: Any) -> Optional[float]:
    if not isinstance(value, str) or not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (datetime.now(timezone.utc) - timestamp).total_seconds())


def _annotate_resolver_availability(data: Dict[str, Any]) -> Dict[str, Any]:
    """Expose persistence freshness explicitly without changing legacy fields."""
    if data.get("availability") in {"degraded", "unavailable"}:
        return data
    try:
        refresh_minutes = max(1, int(data.get("refresh_minutes") or 15))
    except (TypeError, ValueError):
        refresh_minutes = 15
    tick_at = data.get("last_run_at") or data.get("at")
    age_seconds = _resolver_timestamp_age_seconds(tick_at)
    if (
        data.get("source") == "volume"
        and age_seconds is not None
        and age_seconds <= (2 * refresh_minutes * 60)
    ):
        data["availability"] = "available"
        return data
    data["availability"] = "unavailable"
    data["unavailable_reason"] = (
        "persisted_state_stale"
        if data.get("source") == "volume" and age_seconds is not None
        else "persisted_state_absent"
    )
    return data


def _resolver_timeout_fallback(*, error: str, executor_wait_ms: float) -> Dict[str, Any]:
    """Prefer recent shared persisted truth; otherwise expose unavailable honestly."""
    data = _get_cached_resolver_state(allow_stale=True)
    if data is None:
        try:
            from internal.learning.loop_health import cached_resolver_liveness_view

            tick = cached_resolver_liveness_view(allow_stale=True)
        except Exception:
            tick = None
        if isinstance(tick, dict):
            data = {
                **get_prediction_resolver_scheduler_state(),
                "running": bool(tick.get("running")),
                "last_run_at": tick.get("at"),
                "last_run_ok": tick.get("ok"),
                "refresh_minutes": tick.get("refresh_minutes"),
                "worker_peer": tick.get("worker_peer") or {},
                "source": "volume" if tick.get("at") else "memory",
                "stage_timing_ms": dict(tick.get("stage_timing_ms") or {}),
                "active_stage": tick.get("active_stage"),
                "abandoned_live": tick.get("abandoned_live", 0),
            }
    if data is None:
        data = {**get_prediction_resolver_scheduler_state(), "source": "memory"}

    try:
        refresh_minutes = max(1, int(data.get("refresh_minutes") or 15))
    except (TypeError, ValueError):
        refresh_minutes = 15
    tick_at = data.get("last_run_at") or data.get("at")
    age_seconds = _resolver_timestamp_age_seconds(tick_at)
    persisted_recent = (
        data.get("source") == "volume"
        and age_seconds is not None
        and age_seconds <= (2 * refresh_minutes * 60)
    )
    stage_timing_ms = dict(data.get("stage_timing_ms") or {})
    stage_timing_ms["executor_wait"] = round(executor_wait_ms, 1)
    data["stage_timing_ms"] = stage_timing_ms
    data["error"] = error
    data["fallback"] = "recent_persisted" if persisted_recent else "process_memory"
    data["availability"] = "degraded" if persisted_recent else "unavailable"
    if persisted_recent:
        data["fallback_age_seconds"] = round(age_seconds or 0.0, 1)
    else:
        data["unavailable_reason"] = (
            "persisted_state_stale"
            if data.get("source") == "volume" and age_seconds is not None
            else "persisted_state_absent"
        )
    logger.warning(
        "resolver state unavailable=%s error=%s fallback=%s "
        "stage_persistence_ms=%s stage_peer_access_ms=%s stage_executor_wait_ms=%.1f",
        not persisted_recent,
        error,
        data["fallback"],
        stage_timing_ms.get("persistence"),
        stage_timing_ms.get("peer_access"),
        executor_wait_ms,
    )
    return data


@learning_router.get("/api/predictions/resolver")
async def api_predictions_resolver_state():
    executor_started = time.perf_counter()
    try:
        data = await _to_thread_timeout(
            _resolver_state_snapshot,
            RESOLVER_STATE_TIMEOUT,
            label="resolver-state",
        )
        executor_wait_ms = (time.perf_counter() - executor_started) * 1000
        stage_timing_ms = dict(data.get("stage_timing_ms") or {})
        stage_timing_ms["executor_wait"] = round(executor_wait_ms, 1)
        data["stage_timing_ms"] = stage_timing_ms
        logger.info(
            "resolver state stage=executor_wait duration_ms=%.1f",
            executor_wait_ms,
        )
        data = _annotate_resolver_availability(data)
    except asyncio.TimeoutError:
        executor_wait_ms = (time.perf_counter() - executor_started) * 1000
        data = _resolver_timeout_fallback(
            error="timeout",
            executor_wait_ms=executor_wait_ms,
        )
    except Exception as exc:
        logger.warning("resolver state failed: %s", exc)
        executor_wait_ms = (time.perf_counter() - executor_started) * 1000
        data = _resolver_timeout_fallback(
            error="state_unavailable",
            executor_wait_ms=executor_wait_ms,
        )
    return {"status": "success", "data": data}


def _resolver_allowed_on_this_process() -> bool:
    """Prod web serves HTTP only — resolver runs on inline worker."""
    from internal.run_mode import background_on_web, is_worker_mode

    return is_worker_mode() or background_on_web()


def _ensure_resolver_scheduler():
    """Start the resolver scheduler singleton if headless (tests / first trigger)."""
    if not _resolver_allowed_on_this_process():
        return None
    scheduler = get_prediction_resolver_scheduler()
    if scheduler is None:
        start_prediction_resolver_scheduler(immediate=False)
        scheduler = get_prediction_resolver_scheduler()
    try:
        from internal.council.selector_scheduler import get_selector_scheduler_state, start_selector_scheduler

        if not get_selector_scheduler_state().get("running"):
            start_selector_scheduler(immediate=False)
    except Exception:
        pass
    return scheduler


@learning_router.post("/api/learning/trigger")
@limit_or_noop(strict_limit(), override_defaults=True)
async def api_learning_trigger(request: Request):
    """Manually run a prediction-resolution cycle and return scheduler state."""
    if not _resolver_allowed_on_this_process():
        raise HTTPException(
            status_code=503,
            detail="prediction resolver runs on background worker only (BACKGROUND_ON_WEB=off)",
        )
    scheduler = _ensure_resolver_scheduler()
    cycle: Dict[str, Any] = {}
    if scheduler is not None:
        try:
            cycle = scheduler.run_once()
        except Exception as exc:
            cycle = {"ok": False, **public_error(exc, code="resolver_cycle_failed")}

    return {
        "status": "success",
        "data": {
            "cycle": cycle,
            "scheduler": get_prediction_resolver_scheduler_state(),
            "triggered_at": _utcnow_z(),
        },
    }


@learning_router.post("/api/predictions/resolver/run")
@limit_or_noop(strict_limit(), override_defaults=True)
async def api_predictions_resolver_run(request: Request):
    """Trigger a single prediction-resolution cycle on demand."""
    if not _resolver_allowed_on_this_process():
        raise HTTPException(
            status_code=503,
            detail="prediction resolver runs on background worker only (BACKGROUND_ON_WEB=off)",
        )
    scheduler = _ensure_resolver_scheduler()
    if scheduler is None:
        return {
            "status": "error",
            "message": "prediction resolver scheduler is not initialized",
        }
    try:
        result = scheduler.run_once()
        return {"status": "success", "data": result}
    except Exception as exc:
        logger.warning("Manual prediction resolver run failed: %s", exc)
        return {"status": "error", **public_error(exc, code="resolver_run_failed")}


@learning_router.post("/api/learning/pump-lead/recover")
@limit_or_noop(strict_limit(), override_defaults=True)
async def api_pump_lead_recover(request: Request, dry_run: bool = False, hydrate: bool = True):
    """Candle-grade overdue pump_lead backlog (quality filter; no late live prices).

    hydrate=true (default): fetch OHLCV for overdue quality netuids before grading
    so cold price_cache does not burn samples as missing_horizon_candles.
    """
    try:
        from internal.learning.pump_lead_recover import recover_overdue_pump_leads

        summary = recover_overdue_pump_leads(
            dry_run=bool(dry_run), hydrate=bool(hydrate)
        )
        return {"status": "success", "data": summary}
    except Exception as exc:
        logger.warning("pump_lead recover failed: %s", exc)
        return {"status": "error", **public_error(exc, code="pump_lead_recover_failed")}


@learning_router.get("/api/learning/pump-lead/train-status")
async def api_pump_lead_train_status():
    """Upgrade-6 dataset gate: gradeable n, frozen features, ready_to_train."""
    try:
        from internal.learning.pump_lead_train import build_pump_evaluation, dataset_status

        return {
            "status": "success",
            "data": {
                **dataset_status(),
                "evaluation": build_pump_evaluation(),
            },
        }
    except Exception as exc:
        logger.warning("pump_lead train-status failed: %s", exc)
        return {"status": "error", "message": str(exc)}


@learning_router.post("/api/learning/pump-lead/train")
@limit_or_noop(strict_limit(), override_defaults=True)
async def api_pump_lead_train(request: Request, dry_run: bool = True):
    """Export train matrix; fit XGBoost stub only when n>=50 and package present.

    Never swaps prod hand score (ready_for_prod_replace still n>=100 + explicit).
    """
    try:
        from internal.learning.pump_lead_train import train_offline

        summary = train_offline(dry_run=bool(dry_run))
        return {"status": "success", "data": summary}
    except Exception as exc:
        logger.warning("pump_lead train failed: %s", exc)
        return {"status": "error", **public_error(exc, code="pump_lead_train_failed")}


@learning_router.get("/api/scenario-memory")
async def api_scenario_memory():
    """Return the full regime-aware scenario memory snapshot."""
    try:
        from internal.learning.scenario_outcomes import backfill_scenario_outcomes_from_predictions

        backfill_scenario_outcomes_from_predictions()
        return {"status": "ok", **scenario_memory.get_memory_snapshot()}
    except Exception as exc:
        logger.error("Error fetching scenario memory: %s", exc)
        return {
            "status": "error",
            "scenarios": [],
            "regimes": {},
            "stats": {},
            "meta": {},
            "error": str(exc),
        }


@learning_router.post("/api/scenario-memory")
@limit_or_noop(strict_limit(), override_defaults=True)
async def api_scenario_memory_add(request: Request):
    """Record a new regime-aware scenario into persistent memory."""
    try:
        payload = await request.json()
    except Exception as exc:
        return {"status": "error", "error": f"Invalid JSON body: {exc}"}

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
    except Exception as exc:
        logger.error("Error adding scenario: %s", exc)
        return {"status": "error", "error": str(exc)}


@learning_router.get("/api/pick-history")
async def api_pick_history():
    """Pick-of-the-Hour history and aggregate success stats."""
    try:
        return pick_history.get_history(limit=20)
    except Exception as exc:
        logger.warning("pick_history.get_history failed: %s", exc)
        return {
            "active": None,
            "history": [],
            "stats": {"total": 0, "wins": 0, "losses": 0, "success_rate": 0.0},
        }


@learning_router.get("/api/rotation-tracker")
async def api_rotation_tracker():
    """Return subnet rotation patterns and volatility clusters."""
    try:
        subnets = _subnets_for_tracker()
        try:
            from internal import freshness_tracker

            freshness_tracker.mark_updated("rotation")
        except Exception:
            pass
        return {"status": "ok", **rotation_tracker.get_rotation_summary(subnets)}
    except Exception as exc:
        logger.error("Error fetching rotation tracker: %s", exc)
        return {"status": "error", "patterns": [], "volatility_clusters": {}, "error": str(exc)}


@learning_router.get("/api/freshness")
async def api_freshness():
    """Per-section last-updated timestamps for dashboard freshness badges."""
    try:
        from internal import freshness_tracker

        return freshness_tracker.snapshot()
    except Exception as exc:
        logger.warning("freshness snapshot failed: %s", exc)
        return {"last_updated": {}, "now": _utcnow_z()}


@learning_router.get("/api/council/weights")
async def api_council_weights():
    """Return the current Council expert weights."""
    try:
        weights = load_weights_for_ui()
        if isinstance(weights, dict) and weights.get("_proxy_degraded"):
            return {
                "status": "degraded",
                "data": None,
                "weights_degraded": True,
                "error": "worker unreachable",
            }
        return {"status": "success", "data": weights}
    except Exception as exc:
        logger.warning("load_weights failed: %s", exc)
        return {
            "status": "degraded",
            "data": None,
            "weights_degraded": True,
            "error": str(exc),
        }


@learning_router.get("/api/formula-lineage")
async def api_formula_lineage_catalog():
    """Cited formula sources, adaptations, and live learning-loop state per lane."""
    try:
        from internal.council.formula_lineage import build_all_lineage

        return build_all_lineage()
    except Exception as exc:
        logger.warning("formula-lineage catalog failed: %s", exc)
        return {"status": "error", "error": str(exc), "lanes": []}


@learning_router.get("/api/formula-lineage/{lane_id}")
async def api_formula_lineage_lane(lane_id: str):
    """Single lane lineage card (council expert or judge)."""
    try:
        from internal.council.formula_lineage import build_lane_lineage

        lane = build_lane_lineage(lane_id.lower().strip())
        if lane is None:
            raise HTTPException(status_code=404, detail="unknown lane")
        return {"status": "ok", "lane": lane}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("formula-lineage lane failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@learning_router.get("/api/formula-lineage/{lane_id}/evolution")
async def api_formula_evolution_trail(lane_id: str):
    """Time-bounded evolution trail: subnets → learning loop → weight/formula state."""
    try:
        from internal.council.formula_evolution import build_evolution_trail

        trail = build_evolution_trail(lane_id.lower().strip())
        if trail is None:
            raise HTTPException(status_code=404, detail="unknown lane")
        return {"status": "ok", **trail}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("formula evolution trail failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@learning_router.get("/api/weights")
async def api_weights():
    """Return learning stats including expert weights."""
    try:
        return LearningEngine().get_stats()
    except Exception as exc:
        logger.warning("api_weights failed: %s", exc)
        return {"status": "error", "error": str(exc)}


@learning_router.get("/api/resolve-predictions")
async def api_resolve_predictions():
    """Trigger prediction resolution for any due predictions."""
    try:
        weights_before = load_weights()
        subnets = _subnets_for_tracker()
        result = resolver.resolve_due_predictions(subnets)
        return {
            "status": "success",
            "data": result,
            "expert_weights_before": weights_before,
            "expert_weights": load_weights(),
        }
    except Exception as exc:
        logger.warning("resolve_due_predictions failed: %s", exc)
        return {
            "status": "stub",
            "data": {"resolved_now": [], "resolved": [], "pending": [], "stats": {}},
            "error": str(exc),
        }


@learning_router.get("/api/rotation-tokens")
async def api_rotation_tokens():
    """Rotation-token watchlist with live CoinGecko prices (60s cache)."""
    try:
        from internal.council.rotation_tokens import build_rotation_tokens_response

        return build_rotation_tokens_response()
    except Exception as exc:
        logger.warning("rotation-tokens failed: %s", exc)
        return {"status": "error", "tokens": [], "error": str(exc)}


try:
    from internal.message_intel.routes import message_intel_router

    learning_router.include_router(message_intel_router)
except ImportError:
    pass

try:
    from internal.pump_tracker.routes import pump_tracker_router

    learning_router.include_router(pump_tracker_router)
except ImportError as _pump_tracker_exc:
    logger.warning("Pump-tracker routes unavailable: %s", _pump_tracker_exc)

try:
    from internal.calibration.routes import calibration_router

    learning_router.include_router(calibration_router)
except ImportError as _calibration_exc:
    logger.warning("Calibration routes unavailable: %s", _calibration_exc)
