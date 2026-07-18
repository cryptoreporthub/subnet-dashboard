"""Playful post-version nicknames for evolution trail comic relief."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

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

# Short canonical paper / source title → twisted sequel per version bump
_PAPER_SOURCES: Dict[str, str] = {
    "quant": "Advances in Financial Machine Learning",
    "hype": "Delegation Dynamics",
    "dark_horse": "Forecasting Crashes with a Smile",
    "technical": "Technical Analysis of the Financial Markets",
    "oracle": "Meta-Labeling",
    "echo": "On Optimum Character Recognition",
    "pulse": "Returns to Buying Winners and Selling Losers",
}

_PAPER_TWISTS: Dict[str, List[str]] = {
    "quant": [
        "Advances in Subnet Machine Learning",
        "Advances in Emission Machine Learning",
        "Advances in Financial Machine Guessing",
        "Retreats in Financial Machine Learning",
        "Advances in Yield-Curve Reading",
        "Advances in APY Machine Learning",
    ],
    "hype": [
        "Delegation Dynamics for the Rest of Us",
        "Stake Movement as a Lifestyle",
        "On-Chain Vibes: A Field Guide",
        "Hopium Flows in Bittensor",
        "Capital Rotation Theory (TAO Edition)",
        "The Delegator's Lament",
    ],
    "dark_horse": [
        "Forecasting Crashes with a Wince",
        "Forecasting Crashes with a Shrug",
        "Forecasting Crashes with a Frown",
        "Forecasting Crashes with Subnet Emissions",
        "Forecasting Crashes with a Smirk",
        "Forecasting Crashes with a Grimace",
    ],
    "technical": [
        "Technical Analysis of the Subnet Markets",
        "Technical Analysis of the Candlestick Goblin",
        "RSI and the Art of Hoping",
        "Chart Reading for Subnets",
        "Stochastic Reversals and Other Party Tricks",
        "MACD Crosses We Believed In",
    ],
    "oracle": [
        "Meta-Labeling for Subnet Picks",
        "Selective Classification (Now With Receipts)",
        "On Rejecting Bad Ideas Politely",
        "Truth-Telling Under Uncertainty",
        "The Gatekeeper's Guide to Evidence",
        "Meta-Models and Other Trust Issues",
    ],
    "echo": [
        "On Rejecting When Everyone Disagrees",
        "Consensus Without the Group Chat",
        "When to Say 'Probably Not'",
        "Resonance Detection for Committees",
        "Agreement Theory (Subnet Chorus Edition)",
        "The Echo Chamber Strikes Back (Productive Edition)",
    ],
    "pulse": [
        "Returns to Buying Winners (Subnet Remix)",
        "Momentum Until It Isn't",
        "Trends: A Love Story",
        "Price Persistence for Impatient Investors",
        "Riding Waves You're Not Sure About",
        "Momentum Factor (24h Edition)",
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


def version_paper_twist(lane_id: str, version: str) -> Optional[str]:
    """Twist on the lane's cited research title, if we have one."""
    lane = lane_id.lower().strip()
    twists = _PAPER_TWISTS.get(lane)
    if not twists or lane not in _PAPER_SOURCES:
        return None
    return twists[_minor_index(version) % len(twists)]


def paper_source_title(lane_id: str) -> Optional[str]:
    return _PAPER_SOURCES.get(lane_id.lower().strip())


def version_promotion(lane_id: str, version: str, original_label: str) -> Dict[str, Any]:
    """Lane nickname + optional paper-title twist for hybrid promotion episodes."""
    lane = lane_id.lower().strip()
    return {
        "nickname": version_nickname(lane, version, original_label),
        "paper_title": paper_source_title(lane),
        "paper_twist": version_paper_twist(lane, version),
    }
