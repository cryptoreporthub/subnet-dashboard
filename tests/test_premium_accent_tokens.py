"""Guard: premium.css must use violet accent tokens, not hot-pink magenta literals."""

from __future__ import annotations

from pathlib import Path

PREMIUM = Path("static/css/premium.css")
FORBIDDEN = (
    "#ff2bd6",
    "#ff69b4",
    "rgba(255, 0, 255",
    "rgba(255,43,214",
    "rgba(255, 43, 214",
)


def test_premium_css_has_no_hot_pink_magenta_literals():
    text = PREMIUM.read_text(encoding="utf-8")
    for needle in FORBIDDEN:
        assert needle not in text, f"hot-pink literal still in premium.css: {needle}"
    assert "var(--accent-magenta)" in text
    assert "var(--important-border-gradient)" in text
