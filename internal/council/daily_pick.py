"""
Daily pick selector for the Council engine.

Scores every subnet on the 24h horizon, picks the top candidate, and runs
it through the RedTeam audit layer before returning a final payload.

Per-subnet scoring latency is logged (timing only) to
`data/pick_score_latency.jsonl` so cache/parallelization work can be
sized against real distribution data. Logging never alters behavior.

The per-subnet scoring loop runs on a bounded thread pool
(DPICK_MAX_WORKERS, default 4). Baseline run 20260822T131116Z (n=20)
showed ~1712s scoring wall vs ~128 CPU-seconds with an even latency
distribution (top-5 = 53%), i.e. I/O-bound fetch waiting, so fetches are
parallelized rather than cached.
"""

from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any, Dict, List, Optional

import json
import logging
import os
import time

from internal.council.state_vector import (
    attach_council_prediction,
    pick_reasons,
    score_subnet_for_day,
    unpack_score_learning_fields,
)
from internal.council.red_team import audit_daily_pick
from internal.subnets.tradable import tradable_subnets

try:
    from internal.council.weights import effective_weights
except Exception:
    def effective_weights(market_data=None, path=None):
        return {"quant": 0.30, "hype": 0.25, "dark_horse": 0.20, "technical": 0.25}

logger = logging.getLogger(__name__)

LATENCY_PATH = os.environ.get("DPICK_LATENCY_PATH", os.path.join("data", "pick_score_latency.jsonl"))
_DPICK_MAX_WORKERS_DEFAULT = 4
_DPICK_MAX_WORKERS_HARD_CAP = 8


def _parse_dpick_max_workers(raw: Optional[str] = None) -> int:
    """Parse DPICK_MAX_WORKERS; invalid/nonpositive values fall back safely."""
    value = (
        raw
        if raw is not None
        else os.environ.get("DPICK_MAX_WORKERS", str(_DPICK_MAX_WORKERS_DEFAULT))
    )
    try:
        workers = int(value)
    except (TypeError, ValueError):
        workers = _DPICK_MAX_WORKERS_DEFAULT
    if workers < 1:
        workers = _DPICK_MAX_WORKERS_DEFAULT
    return min(workers, _DPICK_MAX_WORKERS_HARD_CAP)


DPICK_MAX_WORKERS = _parse_dpick_max_workers()


def _log_score_latency(
    rows: List[Dict[str, Any]],
    run_id: str,
    score_wall_ms: Optional[float] = None,
) -> None:
    """Append per-subnet scoring latency rows + one summary log line. Best-effort."""
    try:
        if rows:
            os.makedirs(os.path.dirname(LATENCY_PATH) or ".", exist_ok=True)
            with open(LATENCY_PATH, "a") as f:
                for row in rows:
                    f.write(json.dumps(row, sort_keys=True) + "\n")
            times = sorted(float(r["score_ms"]) for r in rows)
            n = len(times)
            p90 = times[min(n - 1, int(round(0.9 * (n - 1))))]
            median = times[n // 2]
            top5 = [
                {"netuid": r.get("netuid"), "subnet": r.get("subnet"), "score_ms": r["score_ms"]}
                for r in sorted(rows, key=lambda x: float(x["score_ms"]), reverse=True)[:5]
            ]
            sum_score_ms = sum(times)
            logger.info(
                "dpick score latency: run_id=%s n=%d sum_score_ms=%.0f score_wall_ms=%.0f median_ms=%.0f p90_ms=%.0f top5=%s",
                run_id,
                n,
                sum_score_ms,
                float(score_wall_ms or 0.0),
                median,
                p90,
                json.dumps(top5),
            )
    except Exception as exc:  # never let logging break a pick
        logger.warning("dpick latency logging failed: %s", exc)


def _weights_for_context(market_context: Dict[str, Any]) -> Dict[str, float]:
    return effective_weights({
        "avg_change_24h": market_context.get("tao_change_24h", 0),
        "breadth": market_context.get("breadth", "neutral"),
        "volatility": market_context.get("volatility", 0),
        "gainers": market_context.get("gainers", 0),
        "losers": market_context.get("losers", 0),
    })


def _remaining_s(deadline_monotonic: Optional[float]) -> Optional[float]:
    if deadline_monotonic is None:
        return None
    return deadline_monotonic - time.monotonic()


def _deadline_exhausted_pick() -> Dict[str, Any]:
    """Low-confidence payload so the engine persists HOLD instead of abandoning."""
    return {
        "subnet": None,
        "score": 0.0,
        "confidence": 0.0,
        "expert_contributions": {},
        "scenario_tags": {},
        "audit": {
            "approved": False,
            "concerns": ["Scoring deadline exceeded"],
            "adjusted_confidence": 0.0,
        },
        "final_confidence": 0.0,
        "action": "long",
        "prediction": None,
        "reasons": [],
        "signal_impact": None,
        "signal_contributions": None,
        "active_signals": [],
    }


def select_daily_pick(
    subnets: List[Dict[str, Any]],
    market_context: Optional[Dict[str, Any]] = None,
    *,
    deadline_monotonic: Optional[float] = None,
) -> Dict[str, Any]:
    market_context = dict(market_context or {})
    market_context.setdefault("weights", _weights_for_context(market_context))
    if "telegram_conviction_rows" not in market_context:
        try:
            from internal.message_intel.rollup import _conviction_rows

            market_context["telegram_conviction_rows"] = _conviction_rows()
        except Exception:
            market_context["telegram_conviction_rows"] = None
    subnets = tradable_subnets(subnets)

    if not subnets:
        return {
            "subnet": None,
            "score": 0.0,
            "confidence": 0.0,
            "expert_contributions": {},
            "scenario_tags": {},
            "audit": {
                "approved": False,
                "concerns": ["No tradable subnets provided"],
                "adjusted_confidence": 0.0,
            },
            "final_confidence": 0.0,
            "action": "long",
            "prediction": None,
            "reasons": [],
            "signal_impact": None,
            "signal_contributions": None,
            "active_signals": [],
        }

    # herd-fix: install single-flight TMC refresh and pre-warm caches sequentially
    # BEFORE workers start, so neither the initial cold miss nor any mid-run TTL
    # expiry can stampede TaoMarketCap from multiple scoring threads.
    remaining = _remaining_s(deadline_monotonic)
    if remaining is not None and remaining <= 0:
        return _deadline_exhausted_pick()
    try:
        from internal.indicators.tmc_singleflight import install_once, prewarm

        install_once()
        if remaining is None or remaining > 2:
            if not prewarm():
                logger.warning("dpick: TMC pre-warm failed; continuing (workers fetch lazily)")
        else:
            logger.warning("dpick: skip TMC pre-warm; %.1fs left on scoring deadline", remaining)
    except Exception as exc:
        logger.warning("dpick: tmc_singleflight unavailable (%s); continuing", exc)

    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())

    cache_session = None
    try:
        from internal.council import pick_score_cache

        cache_session = pick_score_cache.begin_session(market_context)
    except Exception as exc:
        logger.warning("dpick: pick_score_cache unavailable (%s); scoring without cache", exc)

    def _score_one(sn: Dict[str, Any]) -> Dict[str, Any]:
        """Score one subnet and return {subnet, score, latency_row}.

        Latency row capture stays best-effort; a scoring exception propagates
        exactly as it did in the sequential loop.
        """
        t0 = time.perf_counter()
        cache_status = "miss"
        day_score: Dict[str, Any]
        if cache_session is not None:
            from internal.council import pick_score_cache

            cached, cache_status = pick_score_cache.lookup(
                cache_session, int(sn.get("netuid", 0))
            )
            if cached is not None:
                day_score = cached
            else:
                day_score = score_subnet_for_day(sn, market_context)
                if cache_status != "bypass_stale":
                    cache_status = pick_score_cache.store(
                        cache_session, int(sn.get("netuid", 0)), day_score
                    )
        else:
            day_score = score_subnet_for_day(sn, market_context)
        row: Optional[Dict[str, Any]] = None
        try:
            row = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "run_id": run_id,
                "netuid": sn.get("netuid"),
                "subnet": sn.get("name"),
                "score_ms": round((time.perf_counter() - t0) * 1000.0, 1),
                "outcome": "ok",
                "cache": cache_status,
            }
            if cache_session is not None:
                row["epoch_unix"] = cache_session.get("epoch_unix")
        except Exception:
            pass
        return {"subnet": sn, "score": day_score, "latency_row": row}

    # Parallel scoring: results are collected in input (netuid) order via
    # executor.map, preserving the sequential loop's ordering semantics.
    workers = min(DPICK_MAX_WORKERS, len(subnets))
    score_wall_t0 = time.perf_counter()
    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dpick-score")
    try:
        remaining = _remaining_s(deadline_monotonic)
        if remaining is None:
            results = list(executor.map(_score_one, subnets))
        else:
            futs = [executor.submit(_score_one, sn) for sn in subnets]
            done, not_done = wait(futs, timeout=max(0.0, remaining))
            for fut in not_done:
                fut.cancel()
            if not_done:
                logger.warning(
                    "dpick: scoring deadline cut %d/%d subnet jobs",
                    len(not_done),
                    len(subnets),
                )
                results = []
            else:
                results = [fut.result() for fut in futs]
    finally:
        # ponytail: wait=False — scorer failure must not block on peer I/O (scheduler timeout).
        executor.shutdown(wait=False, cancel_futures=True)
    score_wall_ms = round((time.perf_counter() - score_wall_t0) * 1000.0, 1)

    if cache_session is not None:
        try:
            from internal.council import pick_score_cache

            pick_score_cache.end_session(cache_session)
        except Exception as exc:
            logger.warning("dpick: pick_score_cache persist failed (%s)", exc)

    if not results:
        return _deadline_exhausted_pick()

    scored = [{"subnet": r["subnet"], "score": r["score"]} for r in results]
    latency_rows = [r["latency_row"] for r in results if r["latency_row"] is not None]
    _log_score_latency(latency_rows, run_id, score_wall_ms=score_wall_ms)

    scored.sort(key=lambda x: x["score"]["total_score"], reverse=True)
    top = scored[0]
    candidate = top["subnet"]
    score_payload = top["score"]

    tie_break = None
    if len(scored) >= 2:
        runner_up = scored[1]
        score_gap = top["score"]["total_score"] - runner_up["score"]["total_score"]
        if score_gap <= 2.0:
            tie_break = _apply_tie_break(top, runner_up)
            if tie_break.get("winner_changed"):
                candidate = runner_up["subnet"]
                score_payload = runner_up["score"]

    audit_candidate = {**candidate, "confidence": score_payload["confidence"]}
    audit = audit_daily_pick(audit_candidate, subnets)
    final_confidence = audit["adjusted_confidence"]
    learning = unpack_score_learning_fields(score_payload)
    from internal.learning.pick_horizon import day_horizon_hours

    prediction = attach_council_prediction(
        candidate, score_payload, final_confidence, horizon_type="day", horizon_hours=day_horizon_hours()
    )
    reasons = pick_reasons(
        candidate,
        learning["signal_impact"],
        allow_hydration=False,
    )
    try:
        from internal.subnets.impact import impact_profile

        impact = impact_profile(candidate)
    except Exception:
        impact = None

    return {
        "subnet": {
            "netuid": candidate.get("netuid"),
            "name": candidate.get("name"),
            "symbol": candidate.get("symbol"),
        },
        "score": score_payload["total_score"],
        "confidence": score_payload["confidence"],
        "expert_contributions": score_payload["expert_contributions"],
        "scenario_tags": score_payload["scenario_tags"],
        "audit": audit,
        "final_confidence": final_confidence,
        "action": "long",
        "tie_break": tie_break,
        "prediction": prediction,
        "reasons": reasons,
        "impact": impact,
        "signal_impact": learning["signal_impact"],
        "signal_contributions": learning["signal_contributions"],
        "active_signals": learning["active_signals"],
        "telegram_evidence_calibration": score_payload.get("telegram_evidence_calibration"),
    }


def _apply_tie_break(
    leader: Dict[str, Any], runner_up: Dict[str, Any]
) -> Dict[str, Any]:
    l_score = leader["score"]
    r_score = runner_up["score"]
    l_sn = leader["subnet"]
    r_sn = runner_up["subnet"]

    reasons: List[str] = []
    winner_changed = False

    l_conf = float(l_score.get("confidence", 0) or 0)
    r_conf = float(r_score.get("confidence", 0) or 0)
    if r_conf > l_conf + 0.02:
        reasons.append("Runner-up has higher confidence (" + str(round(r_conf, 3)) + " vs " + str(round(l_conf, 3)) + ")")
        winner_changed = True
    elif l_conf > r_conf + 0.02:
        reasons.append("Leader has higher confidence (" + str(round(l_conf, 3)) + " vs " + str(round(r_conf, 3)) + ")")

    l_contrib = l_score.get("expert_contributions", {})
    r_contrib = r_score.get("expert_contributions", {})
    l_qt = float(l_contrib.get("quant", 0)) + float(l_contrib.get("technical", 0))
    r_qt = float(r_contrib.get("quant", 0)) + float(r_contrib.get("technical", 0))
    if not winner_changed and r_qt > l_qt + 0.02:
        reasons.append("Runner-up has higher quant+technical (" + str(round(r_qt, 3)) + " vs " + str(round(l_qt, 3)) + ")")
        winner_changed = True
    elif not winner_changed and l_qt > r_qt + 0.02:
        reasons.append("Leader has higher quant+technical (" + str(round(l_qt, 3)) + " vs " + str(round(r_qt, 3)) + ")")

    if not winner_changed:
        l_vol = abs(float(l_sn.get("price_change_24h", 0) or 0))
        r_vol = abs(float(r_sn.get("price_change_24h", 0) or 0))
        if r_vol < l_vol - 0.5:
            reasons.append("Runner-up has lower 24h volatility (" + str(round(r_vol, 2)) + "% vs " + str(round(l_vol, 2)) + "%)")
            winner_changed = True
        elif l_vol < r_vol - 0.5:
            reasons.append("Leader has lower 24h volatility (" + str(round(l_vol, 2)) + "% vs " + str(round(r_vol, 2)) + "%)")

    if not winner_changed:
        from internal.subnets.impact import relative_flow

        l_flow = relative_flow(l_sn)
        r_flow = relative_flow(r_sn)
        if r_flow > l_flow * 1.15 and r_flow > 0:
            reasons.append(
                "Runner-up has higher relative flow (vol/mcap "
                + str(round(r_flow, 3))
                + " vs "
                + str(round(l_flow, 3))
                + ")"
            )
            winner_changed = True
        elif l_flow > r_flow * 1.15 and l_flow > 0:
            reasons.append(
                "Leader has higher relative flow (vol/mcap "
                + str(round(l_flow, 3))
                + " vs "
                + str(round(r_flow, 3))
                + ")"
            )

    if not reasons:
        reasons.append("Scores within 2.0 but no tie-break rule triggered; leader retained.")

    return {
        "winner_changed": winner_changed,
        "reasons": reasons,
        "leader": {"netuid": l_sn.get("netuid"), "name": l_sn.get("name")},
        "runner_up": {"netuid": r_sn.get("netuid"), "name": r_sn.get("name")},
    }
