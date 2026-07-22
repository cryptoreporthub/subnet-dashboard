"""§21 L11 — Brain letter: today's living narrative (RF-2 honest accuracy)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _trust_block() -> Dict[str, Any]:
    try:
        from internal.council import resolver
        from internal.council.watchdog import check_resolver_watchdog
        from internal.learning.predictions_store import load_predictions
        from internal.learning.trust_stats import build_trust_banner

        stats = resolver.get_resolved_predictions().get("stats", {})
        pending = load_predictions().get("predictions", []) or []
        watchdog = check_resolver_watchdog(pending)
        banner = build_trust_banner(stats, watchdog=watchdog)
        return {
            "trust_banner": banner,
            "brain_ui_ready": banner.get("ready"),
            "watchdog": watchdog,
        }
    except Exception:
        return {
            "trust_banner": {
                "ready": False,
                "headline": None,
                "message": "Learning stats unavailable",
                "graded": 0,
            },
            "brain_ui_ready": False,
            "watchdog": {},
        }


def _judge_citation_block(netuid: Optional[int], subnets: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    if netuid is None:
        return {}
    try:
        from internal.judges.subnet_judges import score_subnet

        row = None
        if subnets:
            for sn in subnets:
                n = sn.get("netuid", sn.get("id"))
                if n is not None and int(n) == int(netuid):
                    row = sn
                    break
        if row is None:
            return {}
        judges = score_subnet(int(netuid), row)
        consensus = judges.get("consensus") or {}
        citations = []
        for lane in ("oracle", "echo", "pulse"):
            block = judges.get(lane) or {}
            if block.get("score") is None:
                continue
            citations.append(
                {
                    "source": f"judge:{lane}",
                    "label": lane.title(),
                    "score": round(float(block.get("score") or 0), 3),
                }
            )
        dissent = None
        if consensus.get("contested") or (
            consensus.get("agreement") is not None and float(consensus["agreement"]) < 0.5
        ):
            ordered = sorted(citations, key=lambda c: c["score"])
            if len(ordered) >= 2 and ordered[-1]["score"] - ordered[0]["score"] >= 0.08:
                dissent = (
                    f"{ordered[0]['label']} most bearish ({ordered[0]['score']:.2f}) · "
                    f"{ordered[-1]['label']} most bullish ({ordered[-1]['score']:.2f})"
                )
        return {
            "citations": citations,
            "consensus": consensus,
            "dissent": dissent,
        }
    except Exception:
        return {}


def _outlook_sentence(pick: Dict[str, Any]) -> str:
    """One forward sentence (≤140 chars) timed to resolve window."""
    action = str(pick.get("action") or "HOLD").upper()
    published = bool(pick.get("published"))
    name = pick.get("name")
    resolves_in = pick.get("resolves_in")
    horizon = str(pick.get("horizon") or pick.get("time_horizon") or "24h")
    trigger = str(pick.get("trigger") or "").strip()
    thesis = str(pick.get("thesis") or "").strip()

    window = f"the next {resolves_in}" if resolves_in else f"the {horizon} window"

    if not name and not published:
        return "No sized call this window — watching the desk into resolve."

    if action in ("LONG", "BUY") and published:
        gist = thesis.split(".")[0] if thesis else "follow-through on the setup"
        sentence = f"Into {window} we expect {gist.lower()} while liquidity holds."
        return sentence[:140]

    if action == "HOLD" and name and not published:
        gate = trigger or "conviction clears a sized long"
        sentence = f"Over {window} we stay flat unless {gate.rstrip('.')}."
        return sentence[:140]

    if action == "HOLD":
        return "No sized call this window — watching the desk into resolve."

    if action in ("SHORT", "SELL", "REDUCE"):
        sentence = f"Over {window} we watch for defensive follow-through on {name or 'this name'}."
        return sentence[:140]

    sentence = f"Over {window} we watch {name or 'the desk'} into resolve."
    return sentence[:140]


def _today_pick_block() -> Dict[str, Any]:
    """File-backed daily pick — avoid live subnet feed + pick engine on letter API."""
    payload: Dict[str, Any] = {}
    subnets: Optional[List[Dict[str, Any]]] = None
    try:
        from server import load_data, _normalize_registry_subnet

        subnets = [
            _normalize_registry_subnet(s) for s in load_data("config/registry.json").values()
        ]
        records = load_data("data/daily_picks.json")
        today = _today_utc()
        if isinstance(records, list):
            for rec in reversed(records):
                if isinstance(rec, dict) and str(rec.get("date") or "")[:10] == today:
                    payload = rec
                    break
    except Exception:
        payload = {}

    enriched = dict(payload) if isinstance(payload, dict) else {}
    try:
        from internal.learning.dpick_copy import attach_brief_to_daily_pick
        from internal.learning.dpick_temporal import attach_temporal_to_daily_pick

        enriched = attach_brief_to_daily_pick(attach_temporal_to_daily_pick(enriched))
    except Exception:
        pass

    pick = enriched.get("pick") if isinstance(enriched.get("pick"), dict) else None
    cand = enriched.get("candidate") if isinstance(enriched.get("candidate"), dict) else None
    block = pick or cand
    subnet = (block or {}).get("subnet") if isinstance((block or {}).get("subnet"), dict) else {}
    netuid = subnet.get("netuid")
    driver = None
    if netuid is not None:
        try:
            from internal.analytics.market_drivers import build_driver_card_for_netuid

            driver = build_driver_card_for_netuid(int(netuid))
        except Exception:
            driver = None

    reasons = (block or {}).get("reasons") if isinstance(block, dict) else []
    why = reasons[0] if reasons else enriched.get("reason")
    brief = enriched.get("brief") if isinstance(enriched.get("brief"), dict) else {}
    judge_block = _judge_citation_block(
        int(netuid) if netuid is not None else None,
        subnets,
    )
    conviction = None
    if isinstance(block, dict):
        for key in ("final_confidence", "confidence", "conviction"):
            if block.get(key) is not None:
                try:
                    conviction = float(block[key])
                    if conviction > 1:
                        conviction = conviction / 100.0
                    break
                except (TypeError, ValueError):
                    pass

    row = {
        "date": enriched.get("date") or _today_utc(),
        "action": str(enriched.get("action") or "HOLD").upper(),
        "published": pick is not None,
        "netuid": netuid,
        "name": subnet.get("name"),
        "symbol": subnet.get("symbol"),
        "why": why,
        "driver_card": driver if isinstance(driver, dict) else None,
        "judge_citations": judge_block.get("citations") or [],
        "dissent": judge_block.get("dissent"),
        "resolves_in": enriched.get("resolves_in"),
        "horizon": enriched.get("time_horizon") or enriched.get("horizon") or "24h",
        "thesis": brief.get("thesis"),
        "trigger": brief.get("trigger"),
        "final_confidence": conviction,
    }
    row["outlook"] = _outlook_sentence(row)
    return row


def _working_block() -> Dict[str, Any]:
    try:
        from internal.analytics.market_drivers import learned_price_drivers

        return learned_price_drivers()
    except Exception:
        return {"ready": False, "top_price_signals": [], "disclaimer": ""}


def _story_block() -> Dict[str, Any]:
    try:
        from internal.learning.story_path import build_story_path

        return build_story_path()
    except Exception:
        return {"data_available": False, "steps": []}


def _yesterday_graded_outcome() -> Optional[str]:
    """One graded outcome from yesterday for S4 lead."""
    try:
        from internal.council import resolver

        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
        for row in reversed(resolver.get_resolved_predictions().get("resolved") or []):
            if not isinstance(row, dict):
                continue
            if str(row.get("created_at") or "")[:10] != yesterday:
                continue
            if row.get("actual_pct") is None:
                continue
            name = row.get("name") or f"SN{row.get('netuid')}"
            hit = row.get("correct")
            label = "HIT" if hit is True else ("MISS" if hit is False else "CLOSED")
            try:
                pct = float(row["actual_pct"])
            except (TypeError, ValueError):
                pct = 0.0
            return f"Yesterday · {name} · {label} · {pct:+.1f}% actual"
    except Exception:
        pass
    return None


def _new_subnet_seed_strip(limit: int = 5) -> List[Dict[str, Any]]:
    """Honest-empty new / high-netuid seed strip."""
    try:
        from server import load_data

        registry = load_data("config/registry.json")
        rows = []
        for sn in registry.values():
            if not isinstance(sn, dict):
                continue
            nu = sn.get("netuid")
            if nu is None:
                continue
            try:
                nu_i = int(nu)
            except (TypeError, ValueError):
                continue
            if nu_i >= 100 or sn.get("is_new"):
                rows.append(
                    {
                        "netuid": nu_i,
                        "name": sn.get("name") or f"SN{nu_i}",
                        "note": "New or recent occupant — verify name on desk",
                    }
                )
        rows.sort(key=lambda r: r["netuid"], reverse=True)
        return rows[:limit]
    except Exception:
        return []


def _todays_desk_block(pick: Dict[str, Any], outlook: str, trust: Dict[str, Any]) -> str:
    """Copyable desk block for S4."""
    banner = trust.get("trust_banner") or {}
    lines = [
        f"SimiVision desk · { _today_utc() }",
        f"Call: {pick.get('action') or 'HOLD'} {pick.get('name') or '—'}",
        f"Outlook: {outlook}",
    ]
    if banner.get("headline"):
        lines.append(f"Trust: {banner['headline']}")
    elif banner.get("graded"):
        lines.append(f"Graded: n={banner.get('graded')}")
    return "\n".join(lines)


def _hold_copy() -> str:
    return "Council on HOLD — confidence hasn't cleared a sized long."


def _render_markdown(
    *,
    date: str,
    pick: Dict[str, Any],
    trust: Dict[str, Any],
    working: Dict[str, Any],
    outlook: str,
) -> str:
    lines = [f"# SimiVision Brain letter — {date}", ""]

    lines.append("## What changed since yesterday")
    banner = trust.get("trust_banner") or {}
    if banner.get("ready") and banner.get("headline"):
        lines.append(f"- {banner['headline']}")
    elif banner.get("message"):
        lines.append(f"- {banner['message']}")
    else:
        lines.append("- Not enough graded picks to quote accuracy yet.")

    signals = working.get("top_price_signals") or []
    if signals:
        for row in signals[:3]:
            sig = row.get("signal") or row.get("tag") or "signal"
            n = row.get("n", 0)
            hr = row.get("hit_rate")
            if hr is not None:
                lines.append(f"- Price signal **{sig}** · {round(hr * 100)}% hit (n={n})")
    else:
        lines.append("- Signal rankings fill in as more picks grade on token price.")
    if working.get("disclaimer"):
        lines.append(f"- _{working['disclaimer']}_")
    lines.append("")

    lines.append("## Today")
    if pick.get("dissent"):
        lines.append(f"- **Council split:** {pick['dissent']}")
    if pick.get("published") and pick.get("name"):
        act = pick.get("action") or "HOLD"
        if act == "LONG":
            act = "BUY"
        label = pick.get("name")
        if pick.get("netuid") is not None:
            label = f"SN{pick['netuid']} {label}"
        lines.append(f"- **{act} {label}**")
        if pick.get("why"):
            lines.append(f"- {pick['why']}")
    elif pick.get("name"):
        lines.append(f"- Candidate: **{pick['name']}** (no audited long yet)")
        if pick.get("why"):
            lines.append(f"- {pick['why']}")
    else:
        lines.append(f"- {_hold_copy()}")

    card = pick.get("driver_card") or {}
    if card.get("status") == "success":
        dec = card.get("decomposition") or {}
        if dec.get("staking_yield_apy") is not None:
            lines.append(
                f"- Staking APY {float(dec['staking_yield_apy']):.1f}% "
                "(income — not token price)"
            )
        if dec.get("price_change_7d") is not None:
            lines.append(f"- Token price 7d: {float(dec['price_change_7d']):+.1f}%")
        if dec.get("yield_trap"):
            lines.append("- **Yield trap** — high APY but token falling")
        for why in (card.get("why") or [])[:2]:
            lines.append(f"- {why}")
    cites = pick.get("judge_citations") or []
    if cites:
        lines.append("- Judges (live):")
        for row in cites[:3]:
            lines.append(f"  - {row.get('label')}: score {row.get('score')}")
    lines.append("")

    lines.append("## Next")
    lines.append(f"- {outlook}")
    lines.append("")

    lines.append("## Integrity")
    wd = trust.get("watchdog") or {}
    if wd.get("warning"):
        lines.append(f"- Resolver watchdog: {wd.get('reason') or 'warning'}")
    exp = banner.get("expired")
    exp_rate = banner.get("expired_rate")
    if exp is not None and exp_rate is not None:
        lines.append(
            f"- Expired backlog: {exp} ({round(float(exp_rate) * 100)}% of ledger)"
        )
    if trust.get("brain_ui_ready"):
        lines.append("- Trust surfaces: **ready**")
    else:
        lines.append("- Trust surfaces: **blocked** until sample + resolver gates clear")
    lines.append("")

    return "\n".join(lines)


def build_brain_letter() -> Dict[str, Any]:
    """Compose today's brain letter from live learning + pick state only."""
    date = _today_utc()
    pick = _today_pick_block()
    trust = _trust_block()
    working = _working_block()
    story = _story_block()
    banner = trust.get("trust_banner") or {}
    outlook = pick.get("outlook") or _outlook_sentence(pick)
    yesterday_outcome = _yesterday_graded_outcome()
    seed_strip = _new_subnet_seed_strip()
    desk_block = _todays_desk_block(pick, outlook, trust)

    empty = (
        not pick.get("name")
        and not banner.get("graded")
        and not (working.get("top_price_signals") or [])
        and not story.get("data_available")
    )

    markdown = _render_markdown(
        date=date,
        pick=pick,
        trust=trust,
        working=working,
        outlook=outlook,
    )

    return {
        "status": "ok",
        "empty": empty,
        "date": date,
        "pick": pick,
        "outlook": outlook,
        "trust_banner": banner,
        "brain_ui_ready": trust.get("brain_ui_ready"),
        "watchdog": trust.get("watchdog"),
        "working": {
            "ready": working.get("ready"),
            "top_price_signals": (working.get("top_price_signals") or [])[:5],
            "disclaimer": working.get("disclaimer"),
        },
        "story_path": {
            "data_available": story.get("data_available"),
            "steps": story.get("steps") or [],
        },
        "markdown": markdown,
        "yesterday_outcome": yesterday_outcome,
        "seed_strip": seed_strip,
        "desk_block": desk_block,
        "source": "/api/letter/brain",
    }
