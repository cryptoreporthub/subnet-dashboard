"""Behavior of the pre-commit hygiene check: what it blocks and what it lets through."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_commit_hygiene.py"
_spec = importlib.util.spec_from_file_location("check_commit_hygiene", SCRIPT)
hyg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hyg)


def test_clean_source_change_passes():
    assert hyg.violations(["internal/judges/postmortems.py", "tests/test_x.py"]) == []


def test_runtime_data_file_is_blocked():
    problems = hyg.violations(["data/postmortems/oracle.json"])
    assert any(
        "runtime file staged: data/postmortems/oracle.json" in p for p in problems
    )


def test_liveness_allowlist_prev_is_blocked():
    problems = hyg.violations(["tests/.liveness_allowlist_prev.json"])
    assert any("tests/.liveness_allowlist_prev.json" in p for p in problems)


def test_scorer_change_without_seed_is_blocked():
    problems = hyg.violations(["internal/council/weights.py"])
    assert any("digest seed" in p for p in problems)


def test_scorer_change_with_seed_passes():
    staged = ["internal/council/weights.py", hyg.SCORER_SEED]
    assert hyg.violations(staged) == []


def test_model_name_in_message_is_blocked_but_plain_message_passes():
    assert hyg.violations([], "fix retry loss\n\nKeeps pick when judge fails.") == []
    problems = hyg.violations([], "fix retry loss\n\nFound by Claude Haiku review.")
    assert any("model name in commit message line 3" in p for p in problems)


def test_repo_file_names_in_message_are_not_model_names():
    message = (
        "Add CLAUDE.md and the .claude/skills guide.\n\n"
        "Claude-only rules stay in CLAUDE.md."
    )
    assert hyg.violations([], message) == []


def test_exact_attribution_trailer_passes():
    message = (
        "Fix retry loss\n\n"
        "Co-Authored-By: Claude Haiku 5.5 <noreply@anthropic.com>\n"
        "Claude-Session: https://claude.ai/code/session_015j9k47guTSMhRzbRougRrX"
    )
    assert hyg.violations([], message) == []


def test_attribution_trailer_for_the_serving_model_passes():
    for family in ("Haiku", "Sonnet", "Opus", "Fable"):
        message = (
            "Fix retry loss\n\n"
            f"Co-Authored-By: Claude {family} 5.5 <noreply@anthropic.com>\n"
            "Claude-Session: https://claude.ai/code/session_015j9k47guTSMhRzbRougRrX"
        )
        assert hyg.violations([], message) == [], family


def test_trailer_look_alikes_and_prose_model_names_are_still_blocked():
    spoofed_email = "Fix\n\nCo-Authored-By: Claude Sonnet 5.5 <someone@example.com>"
    assert hyg.violations([], spoofed_email)
    padded = "Fix\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com> reviewed"
    assert hyg.violations([], padded)
    prose = "Fix\n\nFound by Claude Sonnet 5.5 review."
    assert hyg.violations([], prose)
