"""Nightly selection audit — was published pick oracle #1 at decision time?

Evidence loop (not LLM): replay ``select_daily_pick`` under locked universe policies
and compare to today's persisted row in ``data/daily_picks.json``.

Primary PASS gate: ``scheduler_cap_24`` (matches pick_scheduler universe).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from internal.council.daily_pick import select_daily_pick
from internal.council.publish_gate import publish_gate_fraction, publish_gate_percent
from internal.subnets.scoring_cap import cap_subnets_for_scoring
from internal.subnets.tradable import tradable_subnets, subnet_netuid

logger = logging.getLogger(__name__)

POLICY_SCHEDULER_24 = "scheduler_cap_24"
POLICY_SNAPSHOT_40 = "snapshot_cap_40"
POLICY_FULL = "full_universe"
PRIMARY_POLICY = POLICY_SCHEDULER_24

ALL_POLICIES = (POLICY_SCHEDULER_24, POLICY_SNAPSHOT_40, POLICY_FULL)

PICK_AUDITS_DIR = os.environ.get("PICK_AUDITS_DIR", os.path.join("data", "pick_audits"))
DAILY_PICKS_PATH = os.path.join("data", "daily_picks.json")

_CATEGORY_UNIVERSE = "universe_mismatch"
_CATEGORY_STALE_DATA = "stale_data"
_CATEGORY_GATE_REORDER = "gate_reorder"
_CATEGORY_TIE_BREAK = "tie_break"
_CATEGORY_NO_PUBLISH = "no_publish"
_CATEGORY_PASS = "pass"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _today_str() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _scheduler_cap_limit() -> int:
    top = _env_int("TOP_SCORING_UNIVERSE", 40)
    sched = _env_int("PICK_SCHEDULER_UNIVERSE_CAP", 24)
    return min(sched, top)


def universe_for_policy(
    subnets: List[Dict[str, Any]],
    policy: str,
) -> List[Dict[str, Any]]:
    """Return subnet rows scored for a replay policy."""
    rows = tradable_subnets(subnets)
    if policy == POLICY_SCHEDULER_24:
        return cap_subnets_for_scoring(rows, limit=_scheduler_cap_limit())
    if policy == POLICY_SNAPSHOT_40:
        return cap_subnets_for_scoring(rows, limit=min(40, _env_int("TOP_SCORING_UNIVERSE", 40)))
    if policy == POLICY_FULL:
        return rows
    raise ValueError(f"unknown policy: {policy}")


def _netuid_from_pick_block(block: Optional[Dict[str, Any]]) -> Optional[int]:
    if not isinstance(block, dict):
        return None
    sn = block.get("subnet") if isinstance(block.get("subnet"), dict) else {}
    nu = sn.get("netuid") or block.get("netuid")
    if nu is None:
        return None
    try:
        return int(nu)
    except (TypeError, ValueError):
        return None


def published_netuid_from_row(row: Dict[str, Any]) -> Tuple[Optional[int], str]:
    """Return (netuid, slot) for the audited selection — pick or gated candidate."""
    action = str(row.get("action", "")).upper()
    if action in ("LONG", "LONG"):
        nu = _netuid_from_pick_block(row.get("pick"))
        return nu, "pick"
    if action == "HOLD":
        nu = _netuid_from_pick_block(row.get("candidate"))
        return nu, "candidate"
    nu = _netuid_from_pick_block(row.get("pick"))
    if nu is not None:
        return nu, "pick"
    return _netuid_from_pick_block(row.get("candidate")), "candidate"


def _pick_summary(pick: Dict[str, Any]) -> Dict[str, Any]:
    sn = pick.get("subnet") if isinstance(pick.get("subnet"), dict) else {}
    audit = pick.get("audit") if isinstance(pick.get("audit"), dict) else {}
    return {
        "netuid": sn.get("netuid"),
        "name": sn.get("name"),
        "total_score": float(pick.get("score") or 0),
        "raw_confidence": float(pick.get("confidence") or 0),
        "final_confidence": float(pick.get("final_confidence") or 0),
        "audit_concerns": list(audit.get("concerns") or [])[:6],
        "tie_break": pick.get("tie_break"),
    }


def oracle_for_policy(
    subnets: List[Dict[str, Any]],
    market_context: Optional[Dict[str, Any]],
    policy: str,
) -> Dict[str, Any]:
    universe = universe_for_policy(subnets, policy)
    pick = select_daily_pick(universe, market_context or {})
    return {
        "policy": policy,
        "universe_size": len(universe),
        "universe_netuids": [s.get("netuid") for s in universe[:30]],
        "pick": _pick_summary(pick),
    }


def _has_stale_data_signals(row: Dict[str, Any]) -> bool:
    block = row.get("candidate") or row.get("pick")
    if not isinstance(block, dict):
        return False
    audit = block.get("audit") if isinstance(block.get("audit"), dict) else {}
    concerns = audit.get("concerns") or []
    return any("Missing critical field" in str(c) for c in concerns)


def classify_miss(
    published_nu: Optional[int],
    published_slot: str,
    published_row: Dict[str, Any],
    oracles: Dict[str, Dict[str, Any]],
) -> Tuple[str, str]:
    """Return (verdict, category). verdict is PASS or MISS."""
    primary = oracles.get(PRIMARY_POLICY) or {}
    primary_nu = (primary.get("pick") or {}).get("netuid")
    try:
        primary_nu = int(primary_nu) if primary_nu is not None else None
    except (TypeError, ValueError):
        primary_nu = None

    if published_nu is not None and primary_nu is not None and int(published_nu) == primary_nu:
        return "PASS", _CATEGORY_PASS

    if published_nu is None:
        return "MISS", _CATEGORY_NO_PUBLISH

    full_nu = (oracles.get(POLICY_FULL, {}).get("pick") or {}).get("netuid")
    try:
        full_nu = int(full_nu) if full_nu is not None else None
    except (TypeError, ValueError):
        full_nu = None

    if (
        full_nu is not None
        and int(published_nu) == full_nu
        and primary_nu is not None
        and int(published_nu) != primary_nu
    ):
        return "MISS", _CATEGORY_UNIVERSE

    if _has_stale_data_signals(published_row):
        return "MISS", _CATEGORY_STALE_DATA

    primary_pick = primary.get("pick") or {}
    if primary_pick.get("tie_break") and isinstance(primary_pick["tie_break"], dict):
        if primary_pick["tie_break"].get("winner_changed"):
            return "MISS", _CATEGORY_TIE_BREAK

    # Published differs from primary oracle — gate reorder or generic mismatch
    pub_conf = None
    block = published_row.get("pick") or published_row.get("candidate")
    if isinstance(block, dict):
        pub_conf = block.get("final_confidence")
    try:
        pub_conf_f = float(pub_conf) if pub_conf is not None else None
    except (TypeError, ValueError):
        pub_conf_f = None
    primary_conf = float(primary_pick.get("final_confidence") or 0)
    if pub_conf_f is not None and primary_conf >= publish_gate_fraction() and pub_conf_f < publish_gate_fraction():
        return "MISS", _CATEGORY_GATE_REORDER

    if primary_nu is not None and int(published_nu) != primary_nu:
        return "MISS", _CATEGORY_UNIVERSE

    return "MISS", _CATEGORY_GATE_REORDER


def discovery_questions(
    category: str,
    published_nu: Optional[int],
    published_row: Dict[str, Any],
    oracles: Dict[str, Dict[str, Any]],
) -> Dict[str, str]:
    """Rule-based what/why/rule/devil — same shape as judge postmortems."""
    primary = oracles.get(PRIMARY_POLICY, {}).get("pick") or {}
    full = oracles.get(POLICY_FULL, {}).get("pick") or {}
    p_nu = primary.get("netuid")
    p_name = primary.get("name") or f"SN{p_nu}"
    pub_name = None
    block = published_row.get("pick") or published_row.get("candidate") or {}
    sn = block.get("subnet") if isinstance(block.get("subnet"), dict) else {}
    pub_name = sn.get("name") or f"SN{published_nu}"

    if category == _CATEGORY_PASS:
        return {
            "what": f"Published {pub_name} matched oracle under {PRIMARY_POLICY}.",
            "why": "Selection replay aligned with locked scheduler universe.",
            "rule": "No change required.",
            "devil": "A different universe policy would have chosen another name.",
        }

    if category == _CATEGORY_UNIVERSE:
        what = (
            f"Published {pub_name} (SN{published_nu}) was not oracle under {PRIMARY_POLICY}; "
            f"{p_name} (SN{p_nu}) led scheduler cap-24."
        )
        if full.get("netuid") == published_nu:
            why = (
                "Pick regen or hydrate likely scored the full tradable universe "
                f"while scheduler uses cap-{_scheduler_cap_limit()}."
            )
            rule = (
                "Cap get_or_create_today_pick regen to the same universe as pick_scheduler; "
                "document locked oracle policy in pick-audit-lock.md."
            )
            devil = (
                f"To justify SN{published_nu}, adopt full_universe as primary policy "
                "and accept micro-cap flow tilt."
            )
        else:
            why = "Oracle rankings diverged across universe policies or red-team reorder."
            rule = "Replay all three policies nightly; fix scorer only when primary oracle disagrees."
            devil = "Manual pick_explain on both netuids before changing weights."
        return {"what": what, "why": why, "rule": rule, "devil": devil}

    if category == _CATEGORY_STALE_DATA:
        return {
            "what": f"Published/candidate SN{published_nu} had missing-field audit at pick time.",
            "why": "Subnet hydrate lag — pick written before price/volume landed.",
            "rule": "Regen stale HOLD once prices exist; block persist when critical fields missing.",
            "devil": "If data were complete, oracle might still differ on universe cap.",
        }

    if category == _CATEGORY_GATE_REORDER:
        return {
            "what": f"SN{published_nu} was not primary oracle; red-team or publish gate reordered ranks.",
            "why": f"Oracle SN{p_nu} final_confidence {primary.get('final_confidence')} vs gate {publish_gate_percent()}%.",
            "rule": "Compare raw vs adjusted confidence on published and oracle rows.",
            "devil": "Lowering RED_TEAM_MAX_HAIRCUT may publish a name primary oracle still rejects.",
        }

    if category == _CATEGORY_TIE_BREAK:
        tb = primary.get("tie_break") or {}
        return {
            "what": f"Tie-break changed winner to SN{p_nu}; published was SN{published_nu}.",
            "why": "; ".join(tb.get("reasons") or [])[:200] or "Scores within 2.0 triggered tie-break.",
            "rule": "Log tie_break on every daily row; audit tie-break rules vs human intent.",
            "devil": "Leader raw score may have been higher before tie-break swap.",
        }

    return {
        "what": f"Published SN{published_nu} did not match primary oracle SN{p_nu}.",
        "why": "Unclassified selection miss — inspect oracles and audit concerns.",
        "rule": "Run pick_explain on both netuids; file category in pick-audit-lock.md.",
        "devil": "Outcome resolver may still grade a different question tomorrow.",
    }


def audit_row(
    published_row: Dict[str, Any],
    subnets: List[Dict[str, Any]],
    market_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build audit payload for one daily_picks row (evidence loop core)."""
    published_nu, slot = published_netuid_from_row(published_row)
    oracles: Dict[str, Dict[str, Any]] = {}
    for policy in ALL_POLICIES:
        try:
            oracles[policy] = oracle_for_policy(subnets, market_context, policy)
        except Exception as exc:
            logger.warning("pick audit oracle %s failed: %s", policy, exc)
            oracles[policy] = {"policy": policy, "error": str(exc)}

    verdict, category = classify_miss(published_nu, slot, published_row, oracles)
    questions = discovery_questions(category, published_nu, published_row, oracles)

    block = published_row.get("pick") or published_row.get("candidate") or {}
    published_summary = _pick_summary(block) if isinstance(block, dict) and block.get("subnet") else {}

    return {
        "status": "ok",
        "verdict": verdict,
        "category": category,
        "primary_policy": PRIMARY_POLICY,
        "audited_at": _utcnow_iso(),
        "pick_date": published_row.get("date"),
        "pick_timestamp_utc": published_row.get("timestamp_utc"),
        "action": published_row.get("action"),
        "reason": published_row.get("reason"),
        "published_slot": slot,
        "published": published_summary,
        "published_netuid": published_nu,
        "oracles": oracles,
        "questions": questions,
        "publish_gate": publish_gate_fraction(),
    }


def _find_row_for_date(records: List[Dict[str, Any]], date: str) -> Optional[Dict[str, Any]]:
    for rec in reversed(records):
        if rec.get("date") == date:
            return rec
    return None


def load_daily_picks(path: Optional[str] = None) -> List[Dict[str, Any]]:
    path = path or DAILY_PICKS_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def audit_path_for_date(date: str, base_dir: Optional[str] = None) -> str:
    base = base_dir or PICK_AUDITS_DIR
    return os.path.join(base, f"{date}.json")


def save_audit(payload: Dict[str, Any], path: Optional[str] = None) -> str:
    date = str(payload.get("pick_date") or _today_str())
    out_path = path or audit_path_for_date(date)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, out_path)
    return out_path


def run_audit_for_date(
    subnets: List[Dict[str, Any]],
    market_context: Optional[Dict[str, Any]] = None,
    date: Optional[str] = None,
    *,
    save: bool = True,
) -> Dict[str, Any]:
    """Run selection audit for ``date`` (default today UTC)."""
    date = date or _today_str()
    records = load_daily_picks()
    row = _find_row_for_date(records, date)
    if row is None:
        payload = {
            "status": "no_pick",
            "verdict": "SKIP",
            "category": "no_row",
            "pick_date": date,
            "audited_at": _utcnow_iso(),
            "message": f"No daily_picks row for {date}",
        }
        if save:
            save_audit(payload)
        return payload

    payload = audit_row(row, subnets, market_context)
    if save:
        save_audit(payload)
    return payload


def run_audit_today(
    subnets: List[Dict[str, Any]],
    market_context: Optional[Dict[str, Any]] = None,
    *,
    save: bool = True,
) -> Dict[str, Any]:
    return run_audit_for_date(subnets, market_context, _today_str(), save=save)
