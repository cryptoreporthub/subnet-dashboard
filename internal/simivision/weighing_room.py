"""Conviction Board — Weighing Room presentation fields.

Shapes simivision ``top`` rows into deliberation cards: proximity sort,
NEAR-CALL / WEIGHING / FADING states, Daily Call exclusion, mud bands,
peel receipts, stitch gap whisper, and spine meta.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

NEAR_CALL_MIN_PROXIMITY = 82
FADING_MAX_PROXIMITY = 48
MAX_ROWS = 10
JUDGE_LONG_LIMIT = 6

_EXPERT_DISPLAY = {
    "quant": "Quant",
    "hype": "Hype",
    "dark_horse": "Dark Horse",
    "technical": "Technical",
}
_SKIP_OUTCOMES = frozenset({"duplicate", "expired", "ungradeable"})

_TRIGGER_BY_STATE = {
    "NEAR-CALL": "Clears the bar if conviction holds above today's call level.",
    "WEIGHING": "Needs council alignment and conviction lift past the Daily Call bar.",
    "FADING": "Would need conviction recovery and expert re-alignment.",
}

_BAND_BY_STATE = {
    "NEAR-CALL": ("near", "NEAR A CALL"),
    "WEIGHING": ("watching", "WATCHING"),
    "FADING": ("watching", "WATCHING"),
}

SPINE_WHISPER = "Graded on close · weights update after resolve"

_JUDGE_DISPLAY = ("oracle", "echo", "pulse")
_LONG_VERDICTS = frozenset({"long", "bullish"})


def judge_split_line(judge_scores: Any) -> Optional[str]:
    """Oracle / Echo / Pulse blend for judge-long peel rows."""
    if not isinstance(judge_scores, dict):
        return None
    ranked: List[Tuple[str, float]] = []
    for key in _JUDGE_DISPLAY:
        block = judge_scores.get(key)
        if not isinstance(block, dict):
            continue
        try:
            ranked.append((key.title(), float(block.get("score", 0))))
        except (TypeError, ValueError):
            continue
    if not ranked:
        return None
    ranked.sort(key=lambda x: x[1], reverse=True)
    lead_label, lead_val = ranked[0]
    rest = " / ".join(f"{lab} {val:.2f}" for lab, val in ranked[1:])
    if rest:
        return f"Judge council · {lead_label} leads · {lead_val:.2f} / {rest}"
    return f"Judge council · {lead_label} · {lead_val:.2f}"


def _judge_long_rows(
    subnets: List[Dict[str, Any]],
    *,
    limit: int = JUDGE_LONG_LIMIT,
) -> List[Dict[str, Any]]:
    """Top judge-council rows with unanimous long verdict — never hide from weighing."""
    if not subnets:
        return []
    scored: List[Dict[str, Any]] = []
    try:
        from internal.judges.council_routes import _cap_subnets_for_judges, _load_judges_cache_file
        from internal.judges.subnet_judges import score_all_subnets

        cached = _load_judges_cache_file()
        judges = cached.get("judges") if isinstance(cached, dict) else None
        if isinstance(judges, list) and judges:
            scored = judges
        else:
            capped = _cap_subnets_for_judges(list(subnets))
            scored = score_all_subnets(capped, use_chain=False)
    except Exception:
        return []

    by_netuid: Dict[int, Dict[str, Any]] = {}
    for sn in subnets:
        try:
            by_netuid[int(sn.get("netuid", sn.get("id")))] = sn
        except (TypeError, ValueError):
            continue

    rows: List[Dict[str, Any]] = []
    for item in scored:
        if not isinstance(item, dict):
            continue
        consensus = item.get("consensus") if isinstance(item.get("consensus"), dict) else {}
        verdict = str(consensus.get("verdict") or "").lower()
        if verdict not in _LONG_VERDICTS:
            continue
        nu = item.get("netuid")
        sn = by_netuid.get(int(nu)) if nu is not None else {}
        try:
            conv = int(round(float(consensus.get("score", 0)) * 100))
        except (TypeError, ValueError):
            conv = 0
        from internal.subnets.apy import subnet_apy_percent
        from internal.subnets.tradable import subnet_volume

        apy_val = subnet_apy_percent(sn) if sn else None
        if apy_val is None and sn:
            apy_val = float(sn.get("apy", 0) or 0)
        rows.append(
            {
                "netuid": nu,
                "name": item.get("name"),
                "conviction": conv,
                "judge_long": True,
                "source": "judge_council",
                "judge_scores": {
                    "oracle": item.get("oracle"),
                    "echo": item.get("echo"),
                    "pulse": item.get("pulse"),
                },
                "why_not": (
                    f"Judge consensus {conv}% — Oracle, Echo, and Pulse all above the long bar."
                ),
                "emission": sn.get("emission", 0) if sn else 0,
                "apy": apy_val or 0,
                "volume": subnet_volume(sn) if sn else 0,
                "recommendation": "LONG",
            }
        )
        if len(rows) >= limit:
            break
    rows.sort(key=lambda r: -int(r.get("conviction") or 0))
    return rows


def _merge_weighing_candidates(
    expert_rows: List[Dict[str, Any]],
    judge_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Union expert deliberation + judge-long leaders; dedupe by netuid."""
    merged: Dict[int, Dict[str, Any]] = {}
    for row in expert_rows:
        if not isinstance(row, dict) or row.get("netuid") is None:
            continue
        try:
            nu = int(row["netuid"])
        except (TypeError, ValueError):
            continue
        merged[nu] = dict(row)
        merged[nu]["sources"] = ["expert_council"]
    for row in judge_rows:
        if not isinstance(row, dict) or row.get("netuid") is None:
            continue
        try:
            nu = int(row["netuid"])
        except (TypeError, ValueError):
            continue
        if nu in merged:
            existing = merged[nu]
            existing["judge_long"] = True
            existing["judge_scores"] = row.get("judge_scores")
            existing["sources"] = list(
                dict.fromkeys((existing.get("sources") or []) + ["judge_council"])
            )
            existing["conviction"] = max(
                int(existing.get("conviction") or 0),
                int(row.get("conviction") or 0),
            )
            if not existing.get("why_not"):
                existing["why_not"] = row.get("why_not")
        else:
            merged[nu] = dict(row)
            merged[nu]["sources"] = ["judge_council"]
    out = list(merged.values())
    out.sort(
        key=lambda r: (
            -int(r.get("conviction") or 0),
            0 if r.get("judge_long") else 1,
        )
    )
    return out


def build_weighing_candidates_from_shortlist(
    subnets: List[Dict[str, Any]],
    daily_pick: Optional[Dict[str, Any]] = None,
    market_context: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """Build raw Weighing Room rows from council deliberation alternatives."""
    from internal.learning.dpick_shortlist import build_deliberation_shortlist
    from internal.subnets.apy import subnet_apy_percent
    from internal.subnets.tradable import subnet_volume

    deliberation = build_deliberation_shortlist(
        subnets, market_context or {}, daily_pick
    )
    alternatives = deliberation.get("alternatives") or []
    total_considered = int(deliberation.get("total_considered") or 0)
    min_alts = 1
    if isinstance(daily_pick, dict) and str(daily_pick.get("action", "")).upper() != "HOLD":
        min_alts = 2

    by_netuid: Dict[int, Dict[str, Any]] = {}
    for sn in subnets:
        try:
            by_netuid[int(sn.get("netuid", sn.get("id")))] = sn
        except (TypeError, ValueError):
            continue

    raw_top: List[Dict[str, Any]] = []
    for alt in alternatives:
        if not isinstance(alt, dict):
            continue
        nu = alt.get("netuid")
        sn = by_netuid.get(int(nu)) if nu is not None else {}
        apy_val = subnet_apy_percent(sn) if sn else None
        if apy_val is None and sn:
            apy_val = float(sn.get("apy", 0) or 0)
        raw_top.append(
            {
                "netuid": nu,
                "name": alt.get("name"),
                "conviction": alt.get("conviction", 0),
                "why_not": alt.get("why_not"),
                "expert_contributions": alt.get("expert_contributions") or {},
                "emission": sn.get("emission", 0) if sn else 0,
                "apy": apy_val or 0,
                "volume": subnet_volume(sn) if sn else 0,
                # ponytail: API contract field; UI uses deliberation_state
                "recommendation": "WATCH",
            }
        )

    judge_rows = _judge_long_rows(subnets)
    merged = _merge_weighing_candidates(raw_top, judge_rows)
    if len(alternatives) < min_alts and not merged:
        return [], total_considered
    return merged, total_considered


def conviction_pct(raw: Any) -> int:
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return 0
    if 0.0 <= val <= 1.0:
        val *= 100.0
    return max(0, min(100, int(round(val))))


def proximity_to_call(pick_conv: int, call_conv: Optional[int]) -> int:
    """0–100 closeness to today's call conviction (100 = same bar)."""
    if call_conv is None:
        return max(0, min(100, int(pick_conv)))
    return max(0, min(100, 100 - abs(int(pick_conv) - int(call_conv))))


def deliberation_state(proximity: int, delta: int) -> str:
    if proximity >= NEAR_CALL_MIN_PROXIMITY and delta >= -1:
        return "NEAR-CALL"
    if delta <= -3 or proximity < FADING_MAX_PROXIMITY:
        return "FADING"
    return "WEIGHING"


def expert_split_line(expert_contributions: Any) -> Optional[str]:
    """Council expert blend for peel — Quant/Hype/Dark Horse/Technical only."""
    if not isinstance(expert_contributions, dict):
        return None
    ranked: List[Tuple[str, float]] = []
    for key, label in _EXPERT_DISPLAY.items():
        raw = expert_contributions.get(key)
        if raw is None:
            continue
        try:
            ranked.append((label, float(raw)))
        except (TypeError, ValueError):
            continue
    if not ranked:
        return None
    ranked.sort(key=lambda x: x[1], reverse=True)
    lead_label, lead_val = ranked[0]
    dissent = ""
    if len(ranked) >= 2 and (lead_val - ranked[1][1]) < 0.08:
        dissent = " · dissent"
    rest = " / ".join(f"{lab} {val:.2f}" for lab, val in ranked[1:3])
    if rest:
        return f"Judge split · {lead_label} leads · {lead_val:.2f}{dissent} / {rest}"
    return f"Judge split · {lead_label} leads · {lead_val:.2f}{dissent}"


def gap_whisper(pick_conv: int, call_conv: Optional[int]) -> Optional[str]:
    """Absolute distance whisper for the stitch row."""
    if call_conv is None:
        return None
    gap = abs(int(pick_conv) - int(call_conv))
    if gap == 0:
        return "At the call bar"
    above = int(pick_conv) > int(call_conv)
    if gap >= 9:
        return "Still clear of the call bar" if above else "Still short of the call bar"
    if above:
        return f"{gap} pts above the call bar"
    if gap <= 3:
        return f"{gap} pts below today's call"
    return f"{gap} pts from the call bar"


def trigger_for_state(state: str) -> str:
    return _TRIGGER_BY_STATE.get(state, _TRIGGER_BY_STATE["WEIGHING"])


def band_for_state(state: str) -> Tuple[str, str]:
    return _BAND_BY_STATE.get(state, _BAND_BY_STATE["WEIGHING"])


def mud_band_for_state(state: str) -> Tuple[str, str]:
    """Backward-compatible alias for band_for_state."""
    return band_for_state(state)


def subnet_graded_snippet(netuid: Any) -> str:
    """Honest per-SN track line from predictions ledger."""
    if netuid is None:
        return "No graded call on this SN yet."
    try:
        nu = int(netuid)
    except (TypeError, ValueError):
        return "No graded call on this SN yet."
    try:
        from internal.learning.predictions_store import load_predictions

        data = load_predictions()
    except Exception:
        return "No graded call on this SN yet."

    pending = data.get("predictions") or []
    for pred in pending:
        if not isinstance(pred, dict):
            continue
        try:
            if int(pred.get("netuid")) != nu:
                continue
        except (TypeError, ValueError):
            continue
        if pred.get("status") != "pending":
            continue
        left = pred.get("resolves_in") or ""
        if left:
            return f"Called · pending grade · {left} left"
        return "Called · pending grade"

    hits = 0
    misses = 0
    last: Optional[Dict[str, Any]] = None
    for pred in data.get("resolved") or []:
        if not isinstance(pred, dict):
            continue
        if pred.get("outcome") in _SKIP_OUTCOMES:
            continue
        try:
            if int(pred.get("netuid")) != nu:
                continue
        except (TypeError, ValueError):
            continue
        correct = pred.get("correct")
        if correct is True:
            hits += 1
            last = pred
        elif correct is False:
            misses += 1
            last = pred

    n = hits + misses
    if n == 0 or last is None:
        return "No graded call on this SN yet."

    verdict = "Hit" if last.get("correct") is True else "Miss"
    horizon = last.get("horizon_type") or last.get("horizon") or "24h"
    if horizon == "day":
        horizon = "24h"
    elif horizon == "hour":
        horizon = "1h"
    move = ""
    actual = last.get("actual_pct")
    if actual is not None:
        try:
            move = f" · {float(actual):+.1f}% vs {horizon}"
        except (TypeError, ValueError):
            move = f" · vs {horizon}"
    else:
        move = f" · vs {horizon}"
    line = f"Last call on this SN · {verdict}{move}"
    if n >= 2:
        line += f" · {hits}✓ / {misses}✗ (n={n})"
    return line


def peel_horizon_line(
    *,
    horizon: Optional[str],
    resolves_in: Optional[str],
) -> Optional[str]:
    if not horizon and not resolves_in:
        return None
    hz = horizon or "24h"
    if resolves_in:
        return f"If this became the call · graded on {hz} movement · locks in {resolves_in}"
    return f"If this became the call · graded on {hz} movement"


def _human_updated_ago(updated_at: Optional[str]) -> str:
    if not updated_at:
        return "updated just now"
    try:
        ts = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
    except ValueError:
        return "updated recently"
    age = int((datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds())
    if age < 60:
        return "updated just now"
    if age < 3600:
        return f"updated {age // 60}m ago"
    if age < 86400:
        return f"updated {age // 3600}h ago"
    return f"updated {age // 86400}d ago"


def _near_call_strip(reason: str, *, resolves_in: Optional[str] = None) -> str:
    base = (reason or "conviction holds").strip()
    if len(base) > 64:
        base = base[:61].rstrip() + "…"
    lead = base[:1].lower() + base[1:] if base else "conviction holds"
    if resolves_in:
        return f"Call likely if {lead} · locks in {resolves_in}"
    return f"Call likely if {lead}"


def _delta_for(netuid: Any, conviction: int, last: Dict[str, Any]) -> int:
    key = str(netuid) if netuid is not None else ""
    prev = last.get(key)
    if prev is None:
        return 0
    try:
        return int(round(float(conviction) - float(prev)))
    except (TypeError, ValueError):
        return 0


def _load_last_convictions() -> Dict[str, Any]:
    try:
        from internal.simivision.engine import _load_last_convictions as _load

        return dict(_load() or {})
    except Exception:
        return {}


def _persist_convictions(map_: Dict[str, Any]) -> None:
    try:
        from internal.simivision.engine import _persist_convictions as _save

        _save(map_)
    except Exception:
        pass


def _call_context(
    daily_pick: Optional[Dict[str, Any]],
) -> Tuple[Optional[int], Optional[int], Optional[str], Optional[str]]:
    """Return (netuid, conviction_pct, resolves_in, horizon) from daily pick."""
    if not isinstance(daily_pick, dict):
        return None, None, None, None
    block = None
    for key in ("pick", "candidate"):
        cand = daily_pick.get(key)
        if isinstance(cand, dict) and cand.get("subnet"):
            block = cand
            break
    if block is None and isinstance(daily_pick.get("subnet"), dict):
        block = daily_pick
    netuid = None
    conv = None
    if isinstance(block, dict):
        sn = block.get("subnet") if isinstance(block.get("subnet"), dict) else block
        try:
            if sn.get("netuid") is not None:
                netuid = int(sn["netuid"])
        except (TypeError, ValueError):
            netuid = None
        conv = conviction_pct(
            block.get("final_confidence", block.get("confidence", daily_pick.get("confidence")))
        )
        if conv == 0 and daily_pick.get("final_confidence") is not None:
            conv = conviction_pct(daily_pick.get("final_confidence"))
    resolves_in = daily_pick.get("resolves_in")
    if resolves_in is not None:
        resolves_in = str(resolves_in)
    horizon = daily_pick.get("time_horizon") or daily_pick.get("horizon") or "24h"
    if horizon is not None:
        horizon = str(horizon)
    return netuid, conv if conv and conv > 0 else None, resolves_in, horizon


def weighing_lead_from_rows(
    shaped_rows: List[Dict[str, Any]],
    *,
    beat_conviction: Optional[int] = None,
    skip_netuid: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Best non-primary row from an already-shaped Conviction Board table."""
    from internal.subnets.tradable import is_tradable_subnet

    for row in shaped_rows or []:
        if not isinstance(row, dict) or row.get("primary_call"):
            continue
        nu = row.get("netuid")
        if skip_netuid is not None:
            try:
                if int(nu) == int(skip_netuid):
                    continue
            except (TypeError, ValueError):
                pass
        if not is_tradable_subnet({"netuid": nu}):
            continue
        conv = conviction_pct(row.get("conviction"))
        if beat_conviction is not None and conv <= beat_conviction:
            continue
        return row
    return None


def best_weighing_alternative(
    daily_pick: Optional[Dict[str, Any]],
    subnets: List[Dict[str, Any]],
    *,
    market_context: Optional[Dict[str, Any]] = None,
    beat_conviction: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Lead non-primary weighing row — same ordering as the Conviction Board UI."""
    from internal.subnets.tradable import is_tradable_subnet

    if not subnets:
        return None
    raw_top, total = build_weighing_candidates_from_shortlist(
        subnets, daily_pick, market_context or {}
    )
    rows, _meta = shape_weighing_board(
        raw_top,
        pool_count=total,
        total_considered=total,
        daily_pick=daily_pick,
    )
    for row in rows:
        if not isinstance(row, dict) or row.get("primary_call"):
            continue
        if not is_tradable_subnet({"netuid": row.get("netuid")}):
            continue
        conv = conviction_pct(row.get("conviction"))
        if beat_conviction is not None and conv <= beat_conviction:
            continue
        return row
    return None


def shape_weighing_board(
    top: List[Dict[str, Any]],
    *,
    pool_count: int,
    total_considered: Optional[int] = None,
    daily_pick: Optional[Dict[str, Any]] = None,
    updated_at: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Filter/sort/annotate rows + meta for the Weighing Room UI."""
    call_netuid, call_conv, resolves_in, horizon = _call_context(daily_pick)
    last = _load_last_convictions()
    horizon_line = peel_horizon_line(horizon=horizon, resolves_in=resolves_in)
    rows: List[Dict[str, Any]] = []
    if call_netuid is not None:
        primary_block = None
        if isinstance(daily_pick, dict):
            pick_block = daily_pick.get("pick")
            if isinstance(pick_block, dict) and pick_block.get("subnet"):
                primary_block = pick_block
        primary_subnet = (
            primary_block.get("subnet") if isinstance(primary_block, dict) else {}
        )
        primary_experts = (
            primary_block.get("expert_contributions", {})
            if isinstance(primary_block, dict)
            else {}
        )
        rows.append(
            {
                "netuid": call_netuid,
                "name": primary_subnet.get("name") or f"SN{call_netuid}",
                "conviction": call_conv or 0,
                "proximity": 100,
                "conviction_delta": 0,
                "deliberation_state": "NEAR-CALL",
                "reason": "Published primary daily call",
                "why_not": "This is the published call, not an alternative.",
                "trigger": f"Locks in after the {horizon} resolution window.",
                "expert_contributions": primary_experts,
                "expert_split": expert_split_line(primary_experts),
                "track_record": subnet_graded_snippet(call_netuid),
                "horizon_line": horizon_line,
                "near_call_strip": None,
                "closest_to_call": True,
                "gap_whisper": "PRIMARY DAILY CALL",
                "gap_pts": 0,
                "stitch_border": True,
                "primary_call": True,
                "band": "near",
                "band_label": "PRIMARY CALL",
                "mud_band": "near",
                "mud_label": "PRIMARY CALL",
            }
        )
    for raw in top or []:
        if not isinstance(raw, dict):
            continue
        try:
            nu = int(raw["netuid"]) if raw.get("netuid") is not None else None
        except (TypeError, ValueError):
            nu = None
        if call_netuid is not None and nu == call_netuid:
            continue
        conv = conviction_pct(raw.get("conviction", 0))
        delta = _delta_for(nu, conv, last)
        prox = proximity_to_call(conv, call_conv)
        state = deliberation_state(prox, delta)
        band_slug, band_label = band_for_state(state)
        reasons = raw.get("reasons") if isinstance(raw.get("reasons"), list) else []
        fallback_reason = None
        if call_conv is not None:
            gap = abs(conv - int(call_conv))
            if state == "FADING":
                fallback_reason = f"{gap} pts from today's call — conviction fading"
            elif state == "NEAR-CALL":
                fallback_reason = f"Within {gap} pts of today's call — council still aligning"
            else:
                fallback_reason = f"{gap} pts from call bar — experts still weighing"
        reason = (
            raw.get("reason")
            or raw.get("why_not")
            or raw.get("call_line")
            or (str(reasons[0]) if reasons else None)
            or fallback_reason
            or "Council still weighing this name."
        )
        why_not = (
            raw.get("why_not")
            or (str(reasons[1]) if len(reasons) > 1 else None)
            or "Has not crossed today's call threshold."
        )
        split = expert_split_line(raw.get("expert_contributions"))
        judge_split = judge_split_line(raw.get("judge_scores"))
        if raw.get("judge_long"):
            band_slug, band_label = ("near", "JUDGE LONG")
            if not split and judge_split:
                split = judge_split
            elif split and judge_split:
                split = f"{judge_split} · {split}"
            if raw.get("source") == "judge_council" and not raw.get("expert_contributions"):
                reason = (
                    raw.get("reason")
                    or raw.get("why_not")
                    or "All three judges scored above the long bar."
                )
                why_not = (
                    raw.get("why_not")
                    or "Expert council still sizing conviction on this name."
                )
        row = dict(raw)
        row.update(
            {
                "conviction": conv,
                "proximity": prox,
                "conviction_delta": delta,
                "deliberation_state": state,
                "reason": reason,
                "why_not": why_not,
                "trigger": trigger_for_state(state),
                "expert_split": split,
                "judge_split": judge_split,
                "track_record": subnet_graded_snippet(nu),
                "horizon_line": horizon_line,
                "near_call_strip": (
                    _near_call_strip(str(reason), resolves_in=resolves_in)
                    if state == "NEAR-CALL"
                    else None
                ),
                "closest_to_call": False,
                "gap_whisper": None,
                "gap_pts": None,
                "stitch_border": False,
                "band": band_slug,
                "band_label": band_label,
                "mud_band": band_slug,
                "mud_label": band_label,
            }
        )
        rows.append(row)

    rows.sort(
        key=lambda r: (
            0 if r.get("primary_call") else 1,
            -int(r.get("proximity") or 0),
            -int(r.get("conviction") or 0),
        )
    )
    primary_rows = [r for r in rows if r.get("primary_call")]
    judge_rows = [
        r for r in rows if r.get("judge_long") and not r.get("primary_call")
    ]
    judge_rows.sort(key=lambda r: -int(r.get("conviction") or 0))
    judge_rows = judge_rows[:JUDGE_LONG_LIMIT]
    judge_netuids = {r.get("netuid") for r in judge_rows}
    expert_rows = [
        r
        for r in rows
        if not r.get("primary_call")
        and not r.get("judge_long")
        and r.get("netuid") not in judge_netuids
    ]
    expert_rows.sort(
        key=lambda r: (-int(r.get("proximity") or 0), -int(r.get("conviction") or 0))
    )
    slots_left = max(0, MAX_ROWS - len(primary_rows) - len(judge_rows))
    rows = primary_rows + judge_rows + expert_rows[:slots_left]
    if rows and call_conv is not None:
        primary = next((r for r in rows if r.get("primary_call")), rows[0])
        if not primary.get("primary_call"):
            primary = rows[0]
        primary["closest_to_call"] = True
        if primary.get("primary_call"):
            primary["gap_whisper"] = "PRIMARY DAILY CALL"
            primary["gap_pts"] = 0
            primary["stitch_border"] = True
        else:
            whisper = gap_whisper(int(primary.get("conviction") or 0), call_conv)
            primary["gap_whisper"] = whisper
            primary["gap_pts"] = abs(int(primary.get("conviction") or 0) - int(call_conv))
            primary["stitch_border"] = primary.get("deliberation_state") != "FADING"
    elif rows and call_netuid is not None:
        rows[0]["closest_to_call"] = True

    judge_long_on_table = sum(1 for r in rows if r.get("judge_long"))
    persist_map = {str(r["netuid"]): r["conviction"] for r in rows if r.get("netuid") is not None}
    if persist_map:
        merged = dict(last)
        merged.update(persist_map)
        _persist_convictions(merged)

    excluded = 0
    on_table = len(rows)
    considered = total_considered if total_considered is not None else pool_count
    quiet = max(0, int(considered or 0) - on_table - excluded)
    handoff = None
    if resolves_in:
        handoff = f"Next call locks in {resolves_in} · table freezes then"

    meta = {
        "call_netuid": call_netuid,
        "call_conviction": call_conv,
        "primary_netuid": call_netuid,
        "updated_ago": _human_updated_ago(updated_at),
        "on_table": on_table,
        "quiet_count": quiet,
        "quiet_label": f"{on_table} on table · {quiet} quiet",
        "handoff": handoff,
        "gap_tick_pct": call_conv,
        "spine_whisper": SPINE_WHISPER,
        "horizon": horizon,
        "judge_long_on_table": judge_long_on_table,
    }
    return rows, meta
