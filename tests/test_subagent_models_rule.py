"""Guard the human 2026-08-16 subagent model allowlist."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_subagent_models_rule_names_allowlist():
    rule = (ROOT / ".cursor/rules/subagent-models.mdc").read_text(encoding="utf-8")
    assert "alwaysApply: true" in rule
    assert "composer-2.5" in rule
    assert "gpt-5.6-luna-high" in rule
    assert "Grok 4.7" in rule
    assert "not a hard lane" in rule
    assert "Final pass = the other one" in rule
    assert "Do not spawn a Grok 4.6 subagent to review" not in rule
    assert "Luna high, not Grok" not in rule


def test_old_sonnet_ban_stays_removed():
    # The owner dropped the September Sonnet 4.5/4.6 ban (PR #1621) so the Cursor
    # rules don't clash with the Sonnet pstack subagents Claude Code sessions use.
    paths = (".cursor/rules/subagent-models.mdc", "AGENTS.md",
             "cursor-agents-communication/model-guide.md")
    for path in paths:
        text = (ROOT / path).read_text(encoding="utf-8")
        assert not re.search(r"Sonnet\W*4\.[56]", text), path
        assert "Claude is offline" not in text, path
