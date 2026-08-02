"""Guard: premium.css must use violet accent tokens, not hot-pink magenta literals."""

from __future__ import annotations

import re
from pathlib import Path

PREMIUM = Path("static/css/premium.css")
FORBIDDEN = (
    "#ff2bd6",
    "#ff69b4",
    "rgba(255, 0, 255",
    "rgba(255,43,214",
    "rgba(255, 43, 214",
    "linear-gradient(135deg, #33d4ff",
)


def test_premium_css_has_no_hot_pink_magenta_literals():
    text = PREMIUM.read_text(encoding="utf-8")
    for needle in FORBIDDEN:
        assert needle not in text, f"hot-pink literal still in premium.css: {needle}"
    assert "var(--accent-magenta)" in text
    assert "var(--important-border-gradient)" in text
    assert "var(--board-border-gradient)" in text


def test_premium_badge_tag_selectors_deduped():
    text = PREMIUM.read_text(encoding="utf-8")
    for tag in ("buy", "hold", "sell", "watch"):
        assert len(re.findall(rf"\.badge-{tag},\s*\.tag-{tag}", text)) == 1
        assert not re.search(rf"^\.tag-{tag}\s*\{{", text, re.MULTILINE)
    assert "color: var(--signal-buy) !important" not in text
