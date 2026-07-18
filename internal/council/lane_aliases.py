"""Playful post-version nicknames for evolution trail comic relief."""

from __future__ import annotations

from typing import Dict, List

# ponytail: deterministic by lane + version minor — same bump always same joke
_ALIASES: Dict[str, List[str]] = {
    "quant": [
        "Spreadsheet With Feelings",
        "The Numbers Guy",
        "Kwont (it's still Quant)",
        "Yield Enjoyer Supreme",
        "Fundamentals Department",
        "Excel's Final Boss",
    ],
    "hype": [
        "Hopium Central",
        "The Vibes Department",
        "FOMO Unit",
        "Delegation Hype Man",
        "Momentum's Plus One",
        "Bull Posting Division",
    ],
    "dark_horse": [
        "Darker Horse",
        "Midnight Stallion",
        "Shadow Pony LLC",
        "The Contrarian Strikes Back",
        "Undervaluation Enjoyer",
        "Horse.exe (Dark Mode)",
    ],
    "technical": [
        "Chart Goblin",
        "Candlestick Whisperer",
        "Technically Correct",
        "RSI's Emotional Support Animal",
        "The Indicator Buffet",
        "Lines Go Up Department",
    ],
    "oracle": [
        "Oracle (Unpaid Intern)",
        "The Fact Checker",
        "Truth Teller, Esq.",
        "Evidentiary Affairs",
        "Citation Needed Unit",
        "The Receipts Desk",
    ],
    "echo": [
        "Echo Chamber (Productive Edition)",
        "The Yes-And Department",
        "Consensus Enjoyer",
        "Agreement Enjoyer",
        "Resonance Enjoyer",
        "Vibes Aligned LLC",
    ],
    "pulse": [
        "Pulse Check",
        "The Momentum Gremlin",
        "Heartbeat of the Market",
        "24h Energy Drink",
        "Trend's Plus One",
        "Rhythm Section",
    ],
}


def _minor_index(version: str) -> int:
    parts = str(version or "1.0").strip().lstrip("v").split(".")
    nums = [int(p) for p in parts if p.isdigit()]
    minor = nums[1] if len(nums) > 1 else 0
    return max(0, minor - 1)


def version_nickname(lane_id: str, version: str, original_label: str) -> str:
    """Funny alias for this lane at this council version."""
    aliases = _ALIASES.get(lane_id.lower().strip())
    if not aliases:
        return f"{original_label} (Deluxe)"
    return aliases[_minor_index(version) % len(aliases)]
