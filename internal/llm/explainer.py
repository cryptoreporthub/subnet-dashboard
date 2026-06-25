"""Natural-language explainer for SimiVision picks and market context.

Extracts the inline generate_ai_response logic from server.py into a
reusable module so it can be tested and extended independently.
"""

from typing import Any, Dict, List, Optional


def generate_ai_response(message: str, context: Dict[str, Any]) -> str:
    """Generate a natural-language reply given a user message and market context.

    Parameters
    ----------
    message : str
        The user's chat message.
    context : dict
        Enriched market snapshot with keys ``simivision_picks``,
        ``market_overview``, ``trending``, ``highest_apy``, and ``source``.

    Returns
    -------
    str
        A plain-text reply.
    """
    msg_lower = message.lower()

    if "coldint" in msg_lower or "why" in msg_lower:
        top = _first_pick(context)
        if top:
            return (
                f"Based on SimiVision analysis from {context.get('source', 'taomarketcap.com')}, "
                f"{top['name']} (SN{top['netuid']}) ranks #1 due to high emission "
                f"({top['emission']}%), strong APY ({top['apy']}%), and strong market "
                f"momentum. The AI model detected bullish sentiment with a price change "
                f"of {top['price_change_24h']}% in the last 24h."
            )

    if "apy" in msg_lower:
        top = context.get("highest_apy")
        if top:
            return (
                f"The highest APY subnet is {top['name']} (SN{top['netuid']}) "
                f"at {top['apy']}% with {top['price_change_24h']}% 24h price gain."
            )

    if "trending" in msg_lower or "top" in msg_lower:
        trending = context.get("trending", [])
        if trending:
            items = ", ".join(
                [f"{s['name']} ({s['price_change_24h']}%)" for s in trending]
            )
            return (
                f"Currently trending subnets (by 24h price change): {items}. "
                f"{trending[0]['name']} is seeing the strongest momentum."
            )

    return (
        f"I'm SimiVision AI powered by live {context.get('source', 'taomarketcap.com')} data. "
        "I can explain investment picks, compare subnets, or analyze market trends. "
        "For example: 'Why Coldint?' or 'Show me trending subnets'. "
        "What would you like to know?"
    )


def explain_pick(pick: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> str:
    """Return a one-paragraph explanation for a single SimiVision pick."""
    parts = [
        f"{pick.get('name', 'Unknown')} (rank #{pick.get('rank', '?')})",
    ]
    if "conviction" in pick:
        parts.append(f"conviction {pick['conviction']}%")
    if "rationale" in pick:
        parts.append(pick["rationale"])
    if "recommendation" in pick:
        parts.append(f"recommendation: {pick['recommendation']}")
    return " · ".join(parts)


def _first_pick(context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    picks: List[Dict[str, Any]] = context.get("simivision_picks", [])
    return picks[0] if picks else None