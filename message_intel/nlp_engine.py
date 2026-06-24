"""
NLP Analysis Engine for Telegram message intelligence.

Provides keyword-based sentiment analysis, hype detection, substance scoring,
and entity extraction for TAO/crypto-related messages.
"""

import re
from typing import Any, Dict, List, Optional

# ── Bullish keywords ──────────────────────────────────────────────────
BULLISH_WORDS: List[str] = [
    "bullish", "buy", "long", "pump", "moon", "rocket", "breakout",
    "accumulate", "undervalued", "gem", "opportunity", "upside",
    "green", "growth", "adoption", "partnership", "upgrade",
    "mainnet", "launch", "surge", "rally", "positive", "gains",
    "support", "strong", "momentum", "flipping", "ATH", "high",
    "profitable", "yield", "stake", "dividend", "buying",
    "oversold", "rebound", "reversal", "breakthrough",
]

# ── Bearish keywords ──────────────────────────────────────────────────
BEARISH_WORDS: List[str] = [
    "bearish", "sell", "short", "dump", "crash", "collapse",
    "overvalued", "risk", "decline", "correction", "fud",
    "panic", "capitulation", "bear", "red", "falling",
    "liquidation", "uncertainty", "volatile", "danger",
    "warning", "avoid", "drop", "plunge", "slide", "weak",
    "resistance", "selloff", "overbought", "death",
]

# ── Hype / pump language ──────────────────────────────────────────────
HYPE_WORDS: List[str] = [
    "pump", "moon", "rocket", "x100", "x10", "x1000", "gem",
    "urgent", "now", "fast", "quick", "explosive", "massive",
    "huge", "insane", "crazy", "life-changing", "once in a lifetime",
    "don't miss", "fomo", "limited", "exclusive", "secret",
    "leaked", "insider", "guaranteed", "sure thing", "safe",
    "risk-free", "passive income", "free money", "everyone",
    "next big", "early", "ground floor",
]

# ── Call-to-action phrases ────────────────────────────────────────────
CTA_PHRASES: List[str] = [
    "buy now", "sell now", "get in", "don't miss", "join now",
    "click here", "sign up", "invest now", "act fast",
    "tell everyone", "share this", "spread the word",
]

# ── TAO / Subnet entities ────────────────────────────────────────────
ENTITY_PATTERNS: Dict[str, str] = {
    "subnet_number": r"\b(subnet\s*#?\d+|sn\s*\d+)\b",
    "tao_amount": r"\b(\d+\.?\d*\s*TAO)\b",
    "dtao_amount": r"\b(\d+\.?\d*\s*dTAO)\b",
    "price_usd": r"\b(\$?\d+\.?\d*)\b",
    "protocol": r"\b(Bittensor|TAO|dTAO|Subnet|Alpha|TaoBot|Tensor)\b",
}


class NLPAnalyzer:
    """
    Simple but effective keyword-based NLP analyzer for crypto messages.

    Produces scored analysis dicts with sentiment, hype, substance,
    and entity information.
    """

    def __init__(self):
        self.bullish_set = set(w.lower() for w in BULLISH_WORDS)
        self.bearish_set = set(w.lower() for w in BEARISH_WORDS)
        self.hype_set = set(w.lower() for w in HYPE_WORDS)
        self.cta_list = CTA_PHRASES

    def analyze(self, text: Optional[str]) -> Dict[str, Any]:
        """
        Run full NLP analysis on a message text.

        Returns a dict with sentiment, sentiment_confidence, hype_score,
        substance_score, influence_score, and entities.
        """
        if not text or not text.strip():
            return {
                "sentiment": "neutral",
                "sentiment_confidence": 0.0,
                "hype_score": 0.0,
                "substance_score": 0.0,
                "influence_score": 0.0,
                "entities": {},
            }

        text_lower = text.lower()
        words = re.findall(r"[a-z0-9#$]+", text_lower)

        # ── Sentiment ─────────────────────────────────────────────
        bullish_count = sum(1 for w in words if w in self.bullish_set)
        bearish_count = sum(1 for w in words if w in self.bearish_set)

        total_sentiment_words = bullish_count + bearish_count
        if total_sentiment_words == 0:
            sentiment = "neutral"
            sentiment_confidence = 0.0
        elif bullish_count > bearish_count:
            sentiment = "bullish"
            sentiment_confidence = round(
                bullish_count / total_sentiment_words, 4
            )
        elif bearish_count > bullish_count:
            sentiment = "bearish"
            sentiment_confidence = round(
                bearish_count / total_sentiment_words, 4
            )
        else:
            sentiment = "neutral"
            sentiment_confidence = 0.5

        # ── Hype ──────────────────────────────────────────────────
        hype_count = sum(1 for w in words if w in self.hype_set)
        cta_count = sum(
            1 for phrase in self.cta_list if phrase in text_lower
        )
        raw_hype = (hype_count * 0.15 + cta_count * 0.25)
        hype_score = round(min(1.0, raw_hype), 4)

        # ── Substance ─────────────────────────────────────────────
        substance_score = self._compute_substance(text, words)

        # ── Entities ──────────────────────────────────────────────
        entities = self._extract_entities(text)

        # ── Influence ─────────────────────────────────────────────
        # Blend of sentiment strength + substance + hype
        influence_score = round(
            sentiment_confidence * 0.3 + substance_score * 0.4 + hype_score * 0.3,
            4,
        )

        return {
            "sentiment": sentiment,
            "sentiment_confidence": sentiment_confidence,
            "hype_score": hype_score,
            "substance_score": substance_score,
            "influence_score": influence_score,
            "entities": entities,
        }

    def _compute_substance(self, text: str, words: List[str]) -> float:
        """
        Score how substantive a message is.

        Factors:
        - Mentions specific numbers (price targets, amounts)
        - Mentions specific protocols or projects
        - Message length (short opinions are less substantive)
        - Has specific event references
        """
        score = 0.3  # base

        # Numbers (potential price targets or amounts)
        numbers = re.findall(r"\b\d+\.?\d*\b", text)
        if len(numbers) >= 2:
            score += 0.2
        elif len(numbers) >= 1:
            score += 0.1

        # TAO/dTAO mentions
        if re.search(r"\bTAO\b|\bdTAO\b", text, re.IGNORECASE):
            score += 0.15

        # Protocol / project names
        protocol_matches = re.findall(
            r"\b(Bittensor|Subnet|Alpha|Tensor|TaoBot)\b", text, re.IGNORECASE
        )
        if len(protocol_matches) >= 2:
            score += 0.15

        # Length factor
        word_count = len(words)
        if word_count > 30:
            score += 0.1
        elif word_count > 15:
            score += 0.05

        # URL / link => higher substance (references external info)
        if re.search(r"https?://\S+", text):
            score += 0.1

        return round(min(1.0, score), 4)

    def _extract_entities(self, text: str) -> Dict[str, List[str]]:
        """Extract entities like subnet numbers, TAO amounts, protocols."""
        entities: Dict[str, List[str]] = {
            "subnets": [],
            "tao_amounts": [],
            "dtao_amounts": [],
            "protocols": [],
        }

        for key, pattern in ENTITY_PATTERNS.items():
            matches = re.findall(pattern, text, re.IGNORECASE)
            if key == "subnet_number":
                entities["subnets"] = [m.strip() for m in matches]
            elif key == "tao_amount":
                entities["tao_amounts"] = [m.strip() for m in matches]
            elif key == "dtao_amount":
                entities["dtao_amounts"] = [m.strip() for m in matches]
            elif key == "protocol":
                entities["protocols"] = list(set(m.strip() for m in matches))

        return entities