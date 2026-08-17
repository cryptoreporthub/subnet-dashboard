"""§28 — shareable HTML pages + search API."""

from __future__ import annotations

import asyncio
import html
import logging
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from internal.share_pages.search import global_search
from internal.static_version import STATIC_V

logger = logging.getLogger(__name__)

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
templates = Jinja2Templates(directory=os.path.join(_REPO, "templates"))
templates.env.globals["static_v"] = STATIC_V

share_router = APIRouter(tags=["share"])

SUBNET_SHARE_TIMEOUT = float(os.environ.get("SUBNET_SHARE_TIMEOUT", "8"))


def _partial_subnet_report(netuid: int, *, reason: str) -> Dict[str, Any]:
    return {
        "status": "partial",
        "netuid": netuid,
        "name": f"SN{netuid}",
        "source": "partial",
        "markdown": f"# Subnet SN{netuid}\n\n_Some report sections are still loading ({reason}). Retry shortly._",
        "sections": {},
    }


async def _timed_subnet_report(netuid: int) -> tuple[Dict[str, Any], Optional[str]]:
    from internal.analytics.report import build_subnet_report

    started = time.perf_counter()
    try:
        report = await asyncio.wait_for(
            asyncio.to_thread(build_subnet_report, netuid),
            timeout=SUBNET_SHARE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        elapsed = time.perf_counter() - started
        logger.warning(
            "subnet share: build_subnet_report timed out after %.2fs (limit=%.1fs) netuid=%s",
            elapsed,
            SUBNET_SHARE_TIMEOUT,
            netuid,
        )
        return _partial_subnet_report(netuid, reason="report timeout"), "report_timeout"
    except Exception as exc:
        elapsed = time.perf_counter() - started
        logger.warning(
            "subnet share: build_subnet_report failed after %.2fs netuid=%s: %s",
            elapsed,
            netuid,
            exc,
        )
        return _partial_subnet_report(netuid, reason="report error"), "report_error"

    elapsed = time.perf_counter() - started
    logger.info(
        "subnet share: build_subnet_report %.2fs netuid=%s status=%s",
        elapsed,
        netuid,
        report.get("status"),
    )
    return report, None


async def _timed_explain_subnet(netuid: int) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    def _build() -> Dict[str, Any]:
        from internal.council.pick_explain import explain_subnet
        from internal.subnets.feed import load_pick_subnets

        return explain_subnet(netuid, load_pick_subnets(), {})

    started = time.perf_counter()
    try:
        why_not = await asyncio.wait_for(
            asyncio.to_thread(_build),
            timeout=SUBNET_SHARE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        elapsed = time.perf_counter() - started
        logger.warning(
            "subnet share: explain_subnet timed out after %.2fs (limit=%.1fs) netuid=%s",
            elapsed,
            SUBNET_SHARE_TIMEOUT,
            netuid,
        )
        return None, "explain_timeout"
    except Exception as exc:
        elapsed = time.perf_counter() - started
        logger.debug(
            "subnet share: explain_subnet failed after %.2fs netuid=%s: %s",
            elapsed,
            netuid,
            exc,
        )
        return None, "explain_error"

    elapsed = time.perf_counter() - started
    logger.info("subnet share: explain_subnet %.2fs netuid=%s", elapsed, netuid)
    return why_not, None


def _public_base(request: Request) -> str:
    base = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
    return base or str(request.base_url).rstrip("/")


@share_router.get("/api/search")
async def api_global_search(q: str = Query("", min_length=1), limit: int = Query(8, ge=1, le=20)):
    """Command palette search — subnets, wallets, graded picks."""
    return {"status": "success", "query": q, "results": global_search(q, limit=limit)}


@share_router.get("/subnet/{netuid}")
async def subnet_share_page(request: Request, netuid: int):
    """§28-1 — routable per-subnet analysis page."""
    from internal.analytics.report import markdown_subset_html

    report, report_err = await _timed_subnet_report(netuid)
    why_not, explain_err = await _timed_explain_subnet(netuid)

    name = report.get("name") or f"SN{netuid}"
    judges = (report.get("sections") or {}).get("judges") or {}
    drivers = (report.get("sections") or {}).get("market_drivers") or {}
    consensus = judges.get("consensus") if isinstance(judges, dict) else {}
    base = _public_base(request)
    page_url = f"{base}/subnet/{netuid}"
    title = f"{name} (SN{netuid}) — SimiVision"
    desc = (drivers.get("headline") or f"Council analysis and market drivers for Bittensor subnet {netuid}.")[:200]
    og_image = f"{base}/static/favicon.svg"
    partial_notes: List[str] = []
    if report_err:
        partial_notes.append("Subnet report timed out — showing a partial view.")
    if explain_err:
        partial_notes.append("Council gate notes are still loading.")
    data_available = bool(report) and (
        bool(drivers) or bool(judges) or bool(report.get("markdown"))
    )
    if report.get("status") == "partial":
        data_available = True

    return templates.TemplateResponse(
        request,
        "share/subnet_page.html",
        {
            "netuid": netuid,
            "name": name,
            "report": report,
            "judges": judges,
            "consensus": consensus or {},
            "drivers": drivers,
            "digest_html": markdown_subset_html(report.get("markdown") or ""),
            "data_available": data_available,
            "error_reason": None if data_available else "Subnet report data unavailable",
            "partial_notes": partial_notes,
            "why_not": why_not,
            "page_title": title,
            "page_description": desc,
            "page_url": page_url,
            "og_image_url": og_image,
            "public_base_url": base,
        },
    )


def _wallet_flow_rows(wallet: str, activity: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    if activity and activity.get("status") == "success":
        rows = activity.get("delegation_events") or []
        return rows if isinstance(rows, list) else []
    try:
        from internal.investigation.service import investigate_wallet

        payload = investigate_wallet(wallet, limit=40)
        if payload.get("status") == "success":
            rows = payload.get("delegation_events") or []
            return rows if isinstance(rows, list) else []
    except Exception as exc:
        logger.debug("wallet flow for page failed: %s", exc)
    return []


def _wallet_profile(wallet: str) -> Dict[str, Any]:
    try:
        from internal.whales.service import WhaleIntelligenceService

        profile = WhaleIntelligenceService().get_profile(wallet)
        return profile if isinstance(profile, dict) else {}
    except Exception:
        return {}


def _wallet_subnet_exposure(flow_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aggregate flow rows by netuid for §28-4 mini graph."""
    totals: Dict[int, float] = {}
    for row in flow_rows:
        if not isinstance(row, dict):
            continue
        n = row.get("netuid")
        if n is None:
            continue
        try:
            netuid = int(n)
        except (TypeError, ValueError):
            continue
        amt = row.get("amount_tao") or row.get("amount") or row.get("tao") or 0
        try:
            totals[netuid] = totals.get(netuid, 0.0) + abs(float(amt))
        except (TypeError, ValueError):
            continue
    ranked = sorted(totals.items(), key=lambda x: x[1], reverse=True)
    if not ranked:
        return []
    peak = ranked[0][1] or 1.0
    return [
        {"netuid": n, "amount_tao": round(amt, 4), "pct": round(100.0 * amt / peak, 1)}
        for n, amt in ranked[:8]
    ]


def _wallet_rug_flags(exposure: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rug risk for top exposure subnets (§29-5)."""
    flags: List[Dict[str, Any]] = []
    try:
        from internal.ruggers.watchlist import RuggerWatchlist

        watch = RuggerWatchlist()
        for row in (exposure or [])[:3]:
            netuid = row.get("netuid")
            if netuid is None:
                continue
            risk = watch.get_subnet_risk(int(netuid))
            level = risk.get("risk_level")
            if not level:
                continue
            flags.append(
                {
                    "netuid": int(netuid),
                    "risk_level": level,
                    "rugger_count": risk.get("rugger_count", 0),
                }
            )
    except Exception as exc:
        logger.debug("wallet rug flags failed: %s", exc)
    return flags


@share_router.get("/wallet/{wallet}")
async def wallet_share_page(request: Request, wallet: str):
    """§28-2 — routable wallet explorer page."""
    from internal.investigation.service import investigate_wallet

    wallet = wallet.strip()
    activity = investigate_wallet(wallet, limit=40)
    flow_rows = _wallet_flow_rows(wallet, activity)
    profile = _wallet_profile(wallet)
    exposure = _wallet_subnet_exposure(flow_rows)
    rug_flags = _wallet_rug_flags(exposure)
    data_ok = activity.get("status") == "success"
    base = _public_base(request)
    page_url = f"{base}/wallet/{html.escape(wallet)}"
    short = wallet[:10] + "…" + wallet[-4:] if len(wallet) > 16 else wallet
    title = f"Wallet {short} — SimiVision"
    desc = f"On-chain wallet flows and subnet exposure for {short}."
    og_image = f"{base}/static/favicon.svg"

    return templates.TemplateResponse(
        request,
        "share/wallet_page.html",
        {
            "wallet": wallet,
            "wallet_short": short,
            "activity": activity,
            "flow_rows": flow_rows[:30],
            "profile": profile,
            "exposure": exposure,
            "rug_flags": rug_flags,
            "data_available": data_ok and bool(flow_rows or exposure),
            "error_reason": None if data_ok else activity.get("message", "TaoStats unavailable"),
            "page_title": title,
            "page_description": desc,
            "page_url": page_url,
            "og_image_url": og_image,
            "public_base_url": base,
        },
    )


# ── §28-3 Telegram Listener page (/listener) ──────────────────────────────
# SSR from message-intel engine calls with honest empty fallbacks. The live
# deploy has shown degraded /api/message-intel GETs (422 shared-gating class),
# so every block is individually guarded — the page must never 5xx.


async def _listener_call(fn, default, timeout: float = 6.0):
    """Run a blocking message-intel engine call off-thread with a hard timeout."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn), timeout=timeout)
    except Exception as exc:
        logger.debug("listener page call %s failed: %s", getattr(fn, "__name__", "?"), exc)
        return default


def _as_list(v, default=None):
    return v if isinstance(v, list) else (default or [])


def _safe_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _listener_engine():
    """Lazily import the message-intel engine (module-level import would risk boot)."""
    from internal.message_intel import engine

    return engine


def _listener_worker_json(path: str):
    """Read worker-owned listener data on split_v2; stay local in dev/single-host mode."""
    try:
        from internal.data_volume import needs_worker_volume_proxy

        if not needs_worker_volume_proxy():
            return None
        from internal.worker_proxy import fetch_worker_json_sync

        payload = fetch_worker_json_sync(path, timeout=6)
        return payload if isinstance(payload, dict) else None
    except Exception as exc:
        logger.debug("listener worker read failed %s: %s", path, exc)
        return None


def _listener_message_payload():
    """Canonical listener feed, using the Fly worker volume when the web has no volume."""
    remote = _listener_worker_json("/api/message-intel?limit=24&min_conviction=0")
    if remote is not None:
        return remote
    return _listener_engine().list_messages(limit=24)


def _listener_conviction():
    from internal.conviction_index import get_conviction_snapshot

    return get_conviction_snapshot


def _listener_caller_board():
    from internal.message_intel.rollup import build_telegram_caller_leaderboard

    return build_telegram_caller_leaderboard


async def _listener_page_context() -> Dict[str, Any]:
    from internal.message_intel.listener_service import listener_status
    from internal.message_intel.outcome_loop import outcome_loop_status
    from internal.message_intel.store import live_stats

    ctx: Dict[str, Any] = {
        "listener": await _listener_call(listener_status, {}),
        "outcomes": await _listener_call(outcome_loop_status, {"running": False, "live": False}),
        "store": await _listener_call(live_stats, {"ok": False, "total_messages": 0}),
        "messages": [],
        "trending": [],
        "callers": [],
        "authors": [],
        "reaction_crowns": [],
        "topics": [],
        "divergence": [],
        "subnet_conviction": [],
        "conviction_top": [],
        "summary_text": "",
        "hourly": [],
        "recap": {},
    }

    # On Fly split_v2 the web machine has no SQLite volume. Use the same
    # worker-backed response as /api/message-intel so the page does not render
    # an honest-but-empty local archive while the live API has messages.
    message_payload = await _listener_call(_listener_message_payload, {}, timeout=8)
    message_meta = (
        message_payload.get("meta")
        if isinstance(message_payload, dict) and isinstance(message_payload.get("meta"), dict)
        else {}
    )
    remote_listener = message_meta.get("listener")
    if isinstance(remote_listener, dict):
        ctx["listener"] = remote_listener
    if message_meta:
        ctx["store"] = {
            "ok": bool(message_meta.get("ok", True)),
            "total_messages": int(message_meta.get("total_messages") or 0),
            "high_conviction_count": int(message_meta.get("high_conviction_count") or 0),
        }

    store = ctx["store"] if isinstance(ctx["store"], dict) else {}
    ctx["graded_count"] = int(store.get("total_messages") or 0)
    ctx["high_conviction"] = int(store.get("high_conviction_count") or 0)

    listener = ctx["listener"] if isinstance(ctx["listener"], dict) else {}
    ctx["monitored_group"] = listener.get("monitored_group") or "officialsubnetsummer"
    ctx["group_connected"] = bool(listener.get("group_connected"))
    ctx["display_mode"] = listener.get("display_mode") or "warming"
    ctx["live"] = bool(listener.get("live"))
    age = listener.get("last_message_age_seconds")
    ctx["last_msg_label"] = "—"
    if age is not None:
        try:
            a = float(age)
            if a < 90:
                ctx["last_msg_label"] = f"last msg {int(max(a, 0))}s ago"
            else:
                ctx["last_msg_label"] = f"last msg {int(a // 60)}m ago"
        except (TypeError, ValueError):
            pass

    # messages (live feed) — safe_list/coerce discipline
    msgs_payload = message_payload
    msgs = []
    if isinstance(msgs_payload, dict):
        msgs = _as_list(msgs_payload.get("messages"))
    elif isinstance(msgs_payload, list):
        msgs = msgs_payload
    feed_rows = []
    for m in msgs[:20]:
        if not isinstance(m, dict):
            continue
        netuid = _safe_int(m.get("netuid") or m.get("subnet_id"))
        feed_rows.append(
            {
                "author": m.get("author_name") or m.get("author") or m.get("author_id") or "—",
                "text": m.get("text") or m.get("message") or m.get("content") or "",
                "conviction": (
                    m.get("conviction")
                    if m.get("conviction") is not None
                    else (
                        (m.get("verdict") or {}).get("conviction")
                        if isinstance(m.get("verdict"), dict)
                        else None
                    )
                ),
                "verdict": (
                    (m.get("verdict") or {}).get("predicted_direction")
                    if isinstance(m.get("verdict"), dict)
                    else m.get("verdict")
                ),
                "netuid": netuid,
                "name": m.get("name") or (f"SN{netuid}" if netuid else ""),
                "topic": m.get("topic") or m.get("tags"),
                "ts": m.get("timestamp") or m.get("created_at") or m.get("last_message_at"),
                "base": m.get("base_price") or m.get("baseline") or m.get("reference_price"),
            }
        )
    ctx["feed"] = feed_rows
    ctx["mi_messages"] = [m for m in msgs[:12] if isinstance(m, dict)]

    # trending — subnet telegram conviction (1h lens)
    conv_payload = (
        {"items": message_meta.get("trending")}
        if isinstance(message_meta.get("trending"), list)
        else None
    )
    if not conv_payload or not conv_payload.get("items"):
        try:
            engine = _listener_engine()
            conv_payload = await _listener_call(
                lambda: engine.list_subnet_telegram_conviction(limit=8), None, timeout=6
            )
        except Exception:
            pass
    conv_rows = []
    if isinstance(conv_payload, dict):
        conv_rows = _as_list(
            conv_payload.get("items")
            or conv_payload.get("rows")
            or conv_payload.get("subnets")
            or conv_payload.get("conviction")
        )
    elif isinstance(conv_payload, list):
        conv_rows = conv_payload
    trending = []
    for r in conv_rows[:8]:
        if not isinstance(r, dict):
            continue
        netuid = _safe_int(r.get("netuid"))
        sent = str(r.get("sentiment") or r.get("verdict") or "mixed").lower()
        sent_tag = "bull" if "bull" in sent else ("bear" if "bear" in sent else "mix")
        conv = r.get("conviction") or r.get("index") or r.get("score")
        trending.append(
            {
                "netuid": netuid,
                "name": r.get("name") or (f"SN{netuid}" if netuid else "—"),
                "conviction": conv,
                "sent": sent_tag,
                "mentions": (
                    r.get("mentions")
                    or r.get("call_count")
                    or r.get("count")
                    or r.get("messages")
                ),
            }
        )
    ctx["trending"] = trending
    ctx["subnet_conviction"] = conv_rows

    # The evidence-qualified conviction rollup can be empty while the
    # broader chatter rank still has useful subnet mentions. Keep the desk
    # populated from the canonical ChatterPower rollup in that case.
    if not ctx["trending"]:
        try:
            from internal.message_intel.rollup import build_trending_subnets

            rank_rows = await _listener_call(
                lambda: build_trending_subnets(limit=8, rank_hours=24, window_hours=24),
                [],
                timeout=6,
            )
        except Exception:
            rank_rows = []
        for r in _as_list(rank_rows):
            if not isinstance(r, dict):
                continue
            netuid = _safe_int(r.get("netuid"))
            ctx["trending"].append(
                {
                    "netuid": netuid,
                    "name": r.get("name") or (f"SN{netuid}" if netuid else "—"),
                    "conviction": r.get("avg_conviction") or r.get("conviction"),
                    "sent": str(r.get("sentiment") or "mixed").lower()[:4],
                    "mentions": r.get("mentions"),
                }
            )

    # conviction index top5
    ci_payload = None
    try:
        get_conviction_snapshot = _listener_conviction()
        ci_payload = await _listener_call(
            lambda: get_conviction_snapshot(refresh=False), None, timeout=6
        )
    except Exception:
        pass
    ci_top = []
    if isinstance(ci_payload, dict):
        ci_top = _as_list(ci_payload.get("top5"))
    ctx["conviction_top"] = ci_top
    if not trending and ci_top:
        for r in ci_top[:4]:
            if not isinstance(r, dict):
                continue
            netuid = _safe_int(r.get("netuid"))
            ctx["trending"].append(
                {
                    "netuid": netuid,
                    "name": r.get("name") or (f"SN{netuid}" if netuid else "—"),
                    "conviction": r.get("index") or r.get("conviction"),
                    "sent": "mix",
                    "mentions": r.get("mentions"),
                }
            )

    # callers — resolved qualifying accuracy only
    callers_payload = await _listener_call(
        lambda: _listener_worker_json("/api/message-intel/callers?days=30&limit=8"),
        None,
        timeout=7,
    )
    if callers_payload is None:
        try:
            build_board = _listener_caller_board()
            callers_payload = await _listener_call(
                lambda: build_board(days=30, limit=8), None, timeout=6
            )
        except Exception:
            pass
    caller_rows = []
    if isinstance(callers_payload, dict):
        caller_rows = _as_list(callers_payload.get("callers") or callers_payload.get("authors"))
    elif isinstance(callers_payload, list):
        caller_rows = callers_payload
    callers = []
    for c in caller_rows[:6]:
        if not isinstance(c, dict):
            continue
        total = _safe_int(c.get("total") or c.get("calls") or c.get("resolved"))
        correct = _safe_int(c.get("correct") or c.get("hits"))
        acc = c.get("accuracy") or c.get("hit_rate") or c.get("acc")
        sample_ok = bool(total and total >= 5)
        skin = str(c.get("skin") or "").lower()
        callers.append(
            {
                "author": c.get("author_name") or c.get("author") or c.get("author_id") or "—",
                "acc": acc,
                "total": total,
                "correct": correct,
                "live": _safe_int(c.get("live") or c.get("pending")),
                "sample_ok": sample_ok,
                "staked": bool(c.get("staked")) or skin == "staked",
                "ape": bool(c.get("ape")) or skin == "ape",
            }
        )
    ctx["callers"] = callers

    # authors — weekly champions
    authors_payload = await _listener_call(
        lambda: _listener_worker_json("/api/message-intel/authors?days=7&limit=5"),
        None,
        timeout=7,
    )
    if authors_payload is None:
        try:
            engine = _listener_engine()
            authors_payload = await _listener_call(
                lambda: engine.list_authors(days=7, limit=5), None, timeout=6
            )
        except Exception:
            pass
    author_rows = []
    if isinstance(authors_payload, dict):
        author_rows = _as_list(authors_payload.get("authors") or authors_payload.get("rows"))
    elif isinstance(authors_payload, list):
        author_rows = authors_payload
    authors = []
    for a in author_rows[:4]:
        if not isinstance(a, dict):
            continue
        authors.append(
            {
                "author": a.get("author_name") or a.get("author") or a.get("author_id") or "—",
                "messages": a.get("messages") or a.get("total_messages") or a.get("count"),
                "accuracy": a.get("accuracy") or a.get("hit_rate") or a.get("accuracy_score"),
                "influence": a.get("influence") or a.get("influence_score"),
            }
        )
    ctx["authors"] = authors
    if isinstance(authors_payload, dict):
        crowns = authors_payload.get("reaction_crowns") or []
        if isinstance(crowns, list):
            ctx["reaction_crowns"] = [
                {
                    "emoji": row.get("emoji") or "✨",
                    "label": row.get("label") or row.get("key") or "Reaction",
                    "author": row.get("display_name")
                    or row.get("author_username")
                    or row.get("author_name")
                    or "—",
                    "count": row.get("count") or 0,
                }
                for row in crowns[:6]
                if isinstance(row, dict)
            ]

    # hot topics
    topics_payload = await _listener_call(
        lambda: _listener_worker_json("/api/message-intel/topics?limit=8"),
        None,
        timeout=6,
    )
    if topics_payload is None:
        try:
            engine = _listener_engine()
            topics_payload = await _listener_call(
                lambda: engine.list_topics(limit=8), None, timeout=5
            )
        except Exception:
            pass
    topics = []
    if isinstance(topics_payload, dict):
        t_rows = _as_list(topics_payload.get("topics") or topics_payload.get("rows"))
    elif isinstance(topics_payload, list):
        t_rows = topics_payload
    else:
        t_rows = []
    for t in t_rows[:8]:
        if isinstance(t, str):
            topics.append({"topic": t, "count": None})
        elif isinstance(t, dict):
            topics.append(
                {
                    "topic": t.get("topic") or t.get("tag") or t.get("name") or "—",
                    "count": t.get("count") or t.get("mentions"),
                }
            )
    ctx["topics"] = topics

    # divergence stories
    div_payload = None
    try:
        engine = _listener_engine()
        div_payload = await _listener_call(
            lambda: engine.list_telegram_divergence_stories(days=7, limit=3), None, timeout=6
        )
    except Exception:
        pass
    div_rows = []
    if isinstance(div_payload, dict):
        div_rows = _as_list(
            div_payload.get("stories") or div_payload.get("rows") or div_payload.get("divergence")
        )
    elif isinstance(div_payload, list):
        div_rows = div_payload
    divergence = []
    for d in div_rows[:2]:
        if not isinstance(d, dict):
            continue
        divergence.append(
            {
                "title": d.get("title") or d.get("headline") or "Signal divergence",
                "detail": d.get("summary") or d.get("text") or d.get("detail") or "",
                "netuid": _safe_int(d.get("netuid")),
                "warn": bool(d.get("warn") or d.get("kind") == "warn"),
            }
        )
    ctx["divergence"] = divergence

    # summary text (plain-language recap — prefer yesterday chat narrative)
    yesterday_summary = message_meta.get("yesterday_summary")
    if isinstance(yesterday_summary, dict) and yesterday_summary.get("ready"):
        ctx["summary_text"] = yesterday_summary.get("narrative") or ""
        if yesterday_summary.get("hourly"):
            ctx["hourly"] = [
                {"hour": h["hour"], "pct": h.get("pct", 0)}
                for h in yesterday_summary["hourly"]
            ]
            if yesterday_summary.get("hourly_peak") is not None:
                ctx["hourly_peak"] = yesterday_summary["hourly_peak"]
    else:
        summary_24h = message_meta.get("summary_24h")
        group_pulse = summary_24h.get("group_pulse") if isinstance(summary_24h, dict) else {}
        if isinstance(group_pulse, dict) and group_pulse.get("messages") is not None:
            ctx["summary_text"] = (
                f"{group_pulse.get('messages')} messages in the last 24 hours · "
                f"{group_pulse.get('high_conviction', 0)} high conviction · "
                f"{group_pulse.get('sentiment') or 'Mixed'} average pulse."
            )
        else:
            try:
                from internal.message_intel.summary import summarize_message_intel

                summ = await _listener_call(summarize_message_intel, None, timeout=5)
                if isinstance(summ, dict):
                    ctx["summary_text"] = summ.get("text") or ""
            except Exception as exc:
                logger.debug("listener summary failed: %s", exc)

    if not ctx.get("hourly"):
        # hourly volume from recent messages timestamps (honest; empty until data)
        hourly = {}
        for m in msgs[:200]:
            if not isinstance(m, dict):
                continue
            ts = m.get("timestamp") or m.get("created_at") or m.get("last_message_at")
            if not ts:
                continue
            try:
                hour = int(str(ts)[11:13]) if len(str(ts)) >= 13 else None
            except (TypeError, ValueError):
                hour = None
            if hour is not None:
                hourly[hour] = hourly.get(hour, 0) + 1
        if hourly:
            peak = max(hourly.values())
            ctx["hourly"] = [
                {"hour": h, "pct": round(100 * c / peak) if peak else 0}
                for h, c in sorted(hourly.items())
            ]
            ctx["hourly_peak"] = max(hourly.items(), key=lambda kv: kv[1])[0]

    return ctx


@share_router.get("/listener")
async def listener_page(request: Request):
    """§28-3 — compatibility redirect to the full Telegram desk."""
    return RedirectResponse(url="/subnetsummer", status_code=308)


@share_router.get("/subnetsummer")
async def subnet_summer_page(request: Request):
    """§28-3 — SimiVision Telegram Listener page (SSR + JS hydration)."""
    ctx = await _listener_page_context()
    base = _public_base(request)
    page_url = f"{base}/listener"
    title = "SimiVision — Telegram Listener"
    desc = (
        ctx.get("summary_text")
        or f"Live-graded Telegram signal for {ctx.get('graded_count') or 0} messages across the Bittensor subnet group."
    )[:200]
    og_image = f"{base}/static/og-share.png"
    # §28 canonical/OG: derived from APP_BASE_URL or request.base_url — never localhost.
    ctx.update(
        {
            "page_title": title,
            "page_description": desc,
            "page_url": page_url,
            "og_image_url": og_image,
            "public_base_url": base,
            "request": request,
        }
    )
    return templates.TemplateResponse(request, "listener.html", ctx)


@share_router.get("/subnetsummers", include_in_schema=False)
async def subnet_summers_alias(request: Request):
    """Backward-compatible plural alias for the Telegram listener desk."""
    return await subnet_summer_page(request)