"""Guard: accent tokens live in base.css; badge stacks deduped in ui.css."""

from __future__ import annotations

import re
from pathlib import Path

BASE = Path("static/css/base.css")
UI = Path("static/css/ui.css")
FORBIDDEN = (
    "#ff2bd6",
    "#ff69b4",
    "rgba(255, 0, 255",
    "rgba(255,43,214",
    "rgba(255, 43, 214",
    "linear-gradient(135deg, #33d4ff",
)


def test_base_css_has_no_hot_pink_magenta_literals():
    text = BASE.read_text(encoding="utf-8")
    for needle in FORBIDDEN:
        assert needle not in text, f"hot-pink literal still in base.css: {needle}"
    assert "--accent-magenta: var(--accent-violet)" in text
    assert "--important-border-gradient" in text
    assert "--board-border-gradient" in text


def test_premium_badge_tag_selectors_deduped():
    text = UI.read_text(encoding="utf-8")
    for tag in ("buy", "hold", "sell", "watch"):
        assert len(re.findall(rf"\.badge-{tag},\s*\.tag-{tag}", text)) == 1
        assert not re.search(rf"^\.tag-{tag}\s*\{{", text, re.MULTILINE)
    assert "color: var(--signal-buy) !important" not in text
    assert "var(--accent-magenta)" in text
    assert "var(--important-border-gradient)" in text
    assert "var(--board-border-gradient)" in text
