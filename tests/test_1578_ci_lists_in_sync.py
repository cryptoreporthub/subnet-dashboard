from pathlib import Path
import re


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


def _test_paths(text):
    return set(re.findall(r"tests/test_[\w]+\.py", text))


def _selections():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    triggers, job = workflow.split("jobs:", 1)
    argv = job.split("python -m pytest -q", 1)[1]
    return triggers, _test_paths(triggers), _test_paths(argv), _test_paths(
        GATED.read_text(encoding="utf-8")
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
    ):
        assert f'"{path}"' in triggers


def test_sync_test_is_selected_by_both_gates():
    _, paths, workflow, gated = _selections()
    assert TEST_FILE in paths
    assert TEST_FILE in workflow
    assert TEST_FILE in gated
