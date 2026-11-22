from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/unit1-slice.yml"
GATED = ROOT / "scripts/gated_unit1_pytest.sh"
TEST_FILE = "tests/test_1578_ci_lists_in_sync.py"

GATED_ONLY = {
    "tests/test_dev_radar.py": "Additional local integration coverage",
    "tests/test_endpoint_contract.py": "Additional endpoint coverage",
    "tests/test_graded_chat.py": "Additional local integration coverage",
    "tests/test_phase3_mid_guards_orphan_revive.py": "Specific resolver timing check",
    "tests/test_prediction_loop_closure.py": "Additional closure coverage",
    "tests/test_predictions_write_race.py": "Additional ledger race coverage",
    "tests/test_resolver_scheduler.py": "Additional scheduler coverage",
    "tests/test_tribunal_hero_live.py": "Additional dashboard contract coverage",
}


TEST_PATH = r"tests/test_[\w]+\.py"


def _filter_paths(triggers):
    """Test paths listed as live YAML items. A commented-out item is not a filter."""
    items = re.findall(rf'^\s*-\s*"({TEST_PATH})"\s*$', triggers, flags=re.MULTILINE)
    return set(items)


def _pytest_arguments(text):
    """Test paths in the backslash-continued pytest command, as the shell will run it.

    A comment anywhere in that command is rejected. In bash a comment on a continuation
    line ends the command there, so a commented last argument is silently not run, and
    a commented middle argument turns the next line into its own command.
    """
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if "python -m pytest -q" in line)
    block = [lines[start].split("python -m pytest -q", 1)[1]]
    index = start
    while lines[index].rstrip().endswith("\\") and index + 1 < len(lines):
        index += 1
        block.append(lines[index])
    for line in block:
        assert "#" not in line, f"comment inside the pytest argument list: {line.strip()!r}"
    return set(re.findall(TEST_PATH, "\n".join(block)))


def _split_workflow(workflow):
    triggers, job = workflow.split("jobs:", 1)
    return triggers, job


def _selections():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    triggers, job = _split_workflow(workflow)
    return (
        triggers,
        _filter_paths(triggers),
        _pytest_arguments(job),
        _pytest_arguments(GATED.read_text(encoding="utf-8")),
    )


def test_workflow_and_gated_test_lists_match():
    _, _, workflow, gated = _selections()
    assert workflow - gated == set()
    assert gated - workflow == set(GATED_ONLY)
    assert all(GATED_ONLY.values())


def test_workflow_test_modules_have_path_filters():
    _, paths, workflow, _ = _selections()
    assert paths == workflow


def test_required_source_paths_trigger_unit1():
    triggers, _, _, _ = _selections()
    for path in (
        "internal/judges/**",
        "internal/accuracy_lift/**",
        "internal/background_boot.py",
        "scripts/reset_accuracy_epoch.py",
        "scripts/measure_accuracy_archive.py",
        "scripts/gated_unit1_pytest.sh",
    ):
        assert f'"{path}"' in triggers


def test_sync_test_is_selected_by_both_gates():
    _, paths, workflow, gated = _selections()
    assert TEST_FILE in paths
    assert TEST_FILE in workflow
    assert TEST_FILE in gated


JUDGE_FAILURE_MODULES = (
    "tests/test_judge_failure_keeps_pick.py",
    "tests/test_judge_failure_reconciles_later.py",
)


def test_judge_failure_modules_are_selected_by_every_gate():
    _, paths, workflow, gated = _selections()
    for module in JUDGE_FAILURE_MODULES:
        assert module in paths, module
        assert module in workflow, module
        assert module in gated, module


def _with_line_changed(text, needle, replacement):
    lines = text.split("\n")
    index = next(i for i, line in enumerate(lines) if needle in line)
    lines[index] = replacement(lines[index])
    return "\n".join(lines)


def _last_argument_line(text):
    lines = text.split("\n")
    return next(
        lines[i].strip()
        for i in range(len(lines) - 1, -1, -1)
        if re.fullmatch(rf"\s*{TEST_PATH}\s*\\?", lines[i])
    )


def test_a_commented_out_last_workflow_argument_fails_the_guard():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    _, job = _split_workflow(workflow)
    last = _last_argument_line(job)
    broken = _with_line_changed(job, last, lambda line: line.replace(last, "# " + last))
    with pytest.raises(AssertionError, match="comment inside the pytest argument list"):
        _pytest_arguments(broken)


def test_a_commented_out_middle_gated_argument_fails_the_guard():
    gated = GATED.read_text(encoding="utf-8")
    broken = _with_line_changed(
        gated, "tests/test_soul_map_io_failure.py", lambda line: "  # " + line.strip()
    )
    with pytest.raises(AssertionError, match="comment inside the pytest argument list"):
        _pytest_arguments(broken)


def test_an_inline_comment_after_a_gated_argument_fails_the_guard():
    gated = GATED.read_text(encoding="utf-8")
    broken = _with_line_changed(
        gated, "tests/test_soul_map_io_failure.py", lambda line: line + "  # flaky"
    )
    with pytest.raises(AssertionError, match="comment inside the pytest argument list"):
        _pytest_arguments(broken)


def test_a_commented_out_path_filter_entry_is_not_counted():
    triggers, _ = _split_workflow(WORKFLOW.read_text(encoding="utf-8"))
    target = "tests/test_hold_learning_trail.py"
    assert target in _filter_paths(triggers)
    commented = triggers.replace(f'- "{target}"', f'# - "{target}"')
    assert commented != triggers
    assert target not in _filter_paths(commented)


def test_the_real_files_have_no_comment_inside_their_pytest_commands():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    _pytest_arguments(_split_workflow(workflow)[1])
    _pytest_arguments(GATED.read_text(encoding="utf-8"))
