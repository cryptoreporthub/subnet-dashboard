"""Guard the human 2026-08-16 subagent model allowlist."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_subagent_models_rule_bans_sonnet_4_and_names_allowlist():
    rule = (ROOT / ".cursor/rules/subagent-models.mdc").read_text(encoding="utf-8")
    assert "alwaysApply: true" in rule
    assert "composer-2.5" in rule
    assert "gpt-5.6-luna-high" in rule
    assert "Grok 4.6 medium" in rule
    assert "Sonnet 4.5" in rule and "Sonnet 4.6" in rule
    assert "Do not use Claude Sonnet 4.5 or Sonnet 4.6" in rule
    guide = (ROOT / "cursor-agents-communication/model-guide.md").read_text(encoding="utf-8")
    assert "Never Sonnet 4.5 or Sonnet 4.6" in guide
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "Do **not** spawn Claude Sonnet 4.5 or Sonnet 4.6" in agents
