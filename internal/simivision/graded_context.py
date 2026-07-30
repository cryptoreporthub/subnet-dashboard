"""Graded ledger context for SimiVision chat — cite facts, never invent."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from internal.simivision.weighing_room import subnet_graded_snippet

_MAX_NETUIDS = 2
_ACCURACY_TOKENS = (
    "accuracy",
    "win rate",
    "win-rate",
    "track record",
    "how accurate",
    "how often",
    "graded",
    "correct",
    "council record",
)


def extract_netuids(message: str, *, cap: int = _MAX_NETUIDS) -> List[int]:
    """Pull SN / subnet netuids from a user message (deduped, capped)."""
    text = (message or "").strip()
    if not text:
        return []
    seen: set[int] = set()
    out: List[int] = []
    patterns = (
        r"\b(?:sn|subnet)\s*#?\s*(\d{1,4})\b",
        r"\bSN(\d{1,4})\b",
    )
    for pat in patterns:
        for m in re.finditer(pat, text, re.I):
            try:
                nu = int(m.group(1))
            except (TypeError, ValueError):
                continue
            if nu in seen:
                continue
            seen.add(nu)
            out.append(nu)
            if len(out) >= cap:
                return out
    return out


def wants_trust_stats(message: str) -> bool:
    q = (message or "").lower()
    return any(tok in q for tok in _ACCURACY_TOKENS)


def _daily_pick_summary(daily_pick: Dict[str, Any]) -> Optional[str]:
    if not isinstance(daily_pick, dict) or not daily_pick:
        return None
    pick = daily_pick.get("pick") if isinstance(daily_pick.get("pick"), dict) else daily_pick
    subnet = pick.get("subnet") if isinstance(pick.get("subnet"), dict) else {}
    netuid = subnet.get("netuid") or pick.get("netuid")
    action = pick.get("action") or daily_pick.get("action")
    conviction = pick.get("final_confidence") or pick.get("confidence") or subnet.get("conviction")
    parts: List[str] = []
    if netuid is not None:
        name = subnet.get("name") or pick.get("name") or f"SN{netuid}"
        parts.append(f"Today's council pick: {name} (SN{netuid})")
    if action:
        parts.append(f"action={action}")
    if conviction is not None:
        try:
            parts.append(f"confidence={float(conviction):.0%}")
        except (TypeError, ValueError):
            parts.append(f"confidence={conviction}")
    return " · ".join(parts) if parts else None


def _load_trust_banner() -> Dict[str, Any]:
    try:
        from internal.council import resolver
        from internal.council.watchdog import check_resolver_watchdog
        from internal.learning.predictions_store import load_predictions
        from internal.learning.trust_stats import build_trust_banner

        resolved_stats = resolver.get_resolved_predictions().get("stats", {})
        pending_rows = load_predictions().get("predictions", []) or []
        watchdog = check_resolver_watchdog(pending_rows)
        return build_trust_banner(resolved_stats, watchdog=watchdog)
    except Exception:
        return {
            "ready": False,
            "headline": None,
            "message": "Learning stats unavailable",
            "graded": 0,
        }


def _build_sources(
    subnet_grades: Dict[int, Dict[str, Any]],
    trust_banner: Optional[Dict[str, Any]],
) -> List[Dict[str, str]]:
    sources: List[Dict[str, str]] = []
    for nu, row in sorted(subnet_grades.items()):
        snippet = row.get("snippet") or ""
        if snippet:
            sources.append({"type": "ledger", "id": f"sn{nu}", "label": snippet})
    if trust_banner:
        headline = trust_banner.get("headline") or trust_banner.get("message")
        if headline:
            sources.append({"type": "trust", "id": "council-track-record", "label": str(headline)})
    return sources


def build_graded_context(
    message: str,
    daily_pick: Optional[Dict[str, Any]] = None,
    *,
    include_pick_explain: bool = True,
) -> Dict[str, Any]:
    """Assemble graded accountability facts for chat prompt / offline reply."""
    daily_pick = daily_pick if isinstance(daily_pick, dict) else {}
    netuids = extract_netuids(message)
    q = (message or "").lower()

    if not netuids and any(tok in q for tok in ("today", "daily pick", "council pick", "featured")):
        pick = daily_pick.get("pick") if isinstance(daily_pick.get("pick"), dict) else daily_pick
        subnet = pick.get("subnet") if isinstance(pick.get("subnet"), dict) else {}
        nu = subnet.get("netuid") or pick.get("netuid")
        if nu is not None:
            try:
                netuids = [int(nu)]
            except (TypeError, ValueError):
                pass

    wants_trust = wants_trust_stats(message)
    include_graded = bool(netuids) or wants_trust
    if not include_graded:
        return {
            "active": False,
            "trust_banner": None,
            "daily_pick_summary": None,
            "subnet_grades": {},
            "pick_explain": {},
            "sources": [],
        }

    trust_banner = _load_trust_banner() if wants_trust else None
    daily_summary = None
    if netuids or wants_trust or any(tok in q for tok in ("pick", "today", "council")):
        daily_summary = _daily_pick_summary(daily_pick)

    subnet_grades: Dict[int, Dict[str, Any]] = {}
    for nu in netuids[:_MAX_NETUIDS]:
        snippet = subnet_graded_snippet(nu)
        subnet_grades[nu] = {"snippet": snippet, "netuid": nu}

    pick_explain: Dict[int, Any] = {}
    if include_pick_explain and netuids:
        try:
            from server import _normalize_registry_subnet, load_data

            from internal.council.pick_explain import explain_subnet

            subnets = [
                _normalize_registry_subnet(s) for s in load_data("config/registry.json").values()
            ]
            for nu in netuids[:_MAX_NETUIDS]:
                pick_explain[nu] = explain_subnet(nu, subnets)
        except Exception:
            pick_explain = {}

    sources = _build_sources(subnet_grades, trust_banner)

    return {
        "active": True,
        "trust_banner": trust_banner,
        "daily_pick_summary": daily_summary,
        "subnet_grades": subnet_grades,
        "pick_explain": pick_explain,
        "sources": sources,
    }


def format_graded_prompt_block(graded: Dict[str, Any]) -> str:
    """Serialize graded facts into a prompt appendix."""
    if not graded.get("active"):
        return ""
    lines = [
        "GRADED ACCOUNTABILITY (cite these facts verbatim when relevant; never invent win rates or outcomes):",
        "- If no graded data exists for a subnet, say 'no graded calls yet' — do not speculate.",
    ]
    if graded.get("daily_pick_summary"):
        lines.append(f"- {graded['daily_pick_summary']}")
    banner = graded.get("trust_banner") or {}
    if banner.get("headline"):
        lines.append(f"- Council track record: {banner['headline']}")
    elif banner.get("message"):
        lines.append(f"- Council track record: {banner['message']}")
    for nu, row in sorted((graded.get("subnet_grades") or {}).items()):
        lines.append(f"- SN{nu} ledger: {row.get('snippet')}")
    for nu, expl in sorted((graded.get("pick_explain") or {}).items()):
        if not isinstance(expl, dict):
            continue
        verdict = expl.get("verdict")
        blockers = expl.get("blockers") or expl.get("concerns") or []
        if verdict:
            lines.append(f"- SN{nu} council explain verdict={verdict}")
        if blockers:
            lines.append(f"- SN{nu} gates: {'; '.join(str(b) for b in blockers[:3])}")
    return "\n".join(lines) + "\n\n"


def build_offline_graded_reply(message: str, context: Dict[str, Any]) -> Optional[str]:
    """Deterministic reply from graded facts when the LLM path is unavailable."""
    graded = context.get("graded") or {}
    if not graded.get("active"):
        return None

    parts: List[str] = []
    if wants_trust_stats(message):
        banner = graded.get("trust_banner") or {}
        if banner.get("headline"):
            parts.append(str(banner["headline"]) + ".")
        elif banner.get("message"):
            parts.append(str(banner["message"]) + ".")
        elif banner.get("graded") is not None:
            parts.append(f"Council has {banner['graded']} graded picks on record.")

    for nu, row in sorted((graded.get("subnet_grades") or {}).items()):
        snippet = row.get("snippet") or "No graded call on this SN yet."
        parts.append(f"SN{nu}: {snippet}.")

    if not parts and graded.get("daily_pick_summary"):
        parts.append(str(graded["daily_pick_summary"]) + ".")

    if not parts:
        return None
    return " ".join(parts[:4])
