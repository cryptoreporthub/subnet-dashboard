"""Lightweight topic tags for message-intel feed (keyword classify on read)."""

from __future__ import annotations

import re
from typing import List, Sequence, Tuple

# (tag, keyword patterns) — order preserved for stable chip order
_TOPIC_RULES: Tuple[Tuple[str, Sequence[str]], ...] = (
    ("validator", ("validator", "validators", "staking", "stake", "delegate", "nominator")),
    ("emissions", ("emission", "emissions", "inflation", "halving", "mint", "burn")),
    ("alpha", ("alpha", "apy", "yield", "returns", "outperform")),
    ("partnership", ("partnership", "partner", "collab", "collaboration", "integration", "integrat")),
    ("market", ("price", "pump", "dump", "market", "cap", "tao", "bull", "bear")),
)

_TAG_ORDER = {tag: i for i, (tag, _) in enumerate(_TOPIC_RULES)}


def classify_message_topics(text: str) -> List[str]:
    """Return starter topic tags for a message body (no LLM, English keywords)."""
    if not text or not str(text).strip():
        return []
    hay = str(text).lower()
    found: List[str] = []
    for tag, keywords in _TOPIC_RULES:
        for kw in keywords:
            if re.search(r"\b" + re.escape(kw), hay):
                found.append(tag)
                break
    found.sort(key=lambda t: _TAG_ORDER.get(t, 99))
    return found
