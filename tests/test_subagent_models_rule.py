"""Guard the human 2026-08-16 subagent model allowlist."""

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
