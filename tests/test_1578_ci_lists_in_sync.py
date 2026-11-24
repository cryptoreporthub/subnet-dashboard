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
COMMAND = re.compile(r"^\s*(exec )?python -m pytest -q \\$")
ARGUMENT = re.compile(rf"^\s*({TEST_PATH})(::\w+)?( \\)?$")
FORWARD_ARGS = '"$@"'


def _command_block(text):
    """The backslash-continued pytest command, exactly as the shell reads it.

    The first line must be exactly 'python -m pytest -q \\' (the script may prefix
    'exec'), and every line after it must be one bare test path, until the first line
    that does not end in a backslash. Anything else is rejected: a comment, a flag such
    as --co or -k, a node id, a quoted path, or a wrapper. In bash a comment on a
    continuation line ends the command there, so a commented last argument is silently
    not run, and flags change which tests run without changing which paths are listed.
    """
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if COMMAND.match(line)]
    assert starts, "no 'python -m pytest -q \\' command line found"
    assert len(starts) == 1, "more than one 'python -m pytest -q \\' command line"
    index = starts[0]
    block = [lines[index]]
    while block[-1].endswith("\\") and index + 1 < len(lines):
        index += 1
        line = lines[index]
        assert "#" not in line, f"comment inside the pytest argument list: {line.strip()!r}"
        assert ARGUMENT.match(line) or line.strip() == FORWARD_ARGS, (
            f"unexpected content in the pytest argument list: {line.strip()!r}"
        )
        block.append(line)
    return block


def _pytest_arguments(text):
    paths = []
    for line in _command_block(text)[1:]:
        match = ARGUMENT.match(line)
        if match is None:
            continue
        path, node_id = match.group(1), match.group(2)
        assert node_id is None or path in GATED_ONLY, (
            f"a node id narrows a test path that is not allowed one: {line.strip()!r}"
        )
        paths.append(path)
    assert len(paths) == len(set(paths)), "a test path is listed twice"
    return set(paths)


def _split_workflow(workflow):
    parts = re.split(r"^jobs:\s*$", workflow, maxsplit=1, flags=re.MULTILINE)
    assert len(parts) == 2, "no top-level jobs: key found"
    return parts[0], parts[1]


def _selections():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    triggers, job = _split_workflow(workflow)
    return (
        triggers,
        _pytest_arguments(job),
        _pytest_arguments(GATED.read_text(encoding="utf-8")),
    )


def test_workflow_and_gated_test_lists_match():
    _, workflow, gated = _selections()
    assert workflow - gated == set()
    assert gated - workflow == set(GATED_ONLY)
    assert all(GATED_ONLY.values())


def test_sync_and_judge_failure_modules_are_in_both_test_lists():
    _, workflow, gated = _selections()
    for module in (
        TEST_FILE,
        "tests/test_judge_failure_keeps_pick.py",
        "tests/test_judge_failure_reconciles_later.py",
    ):
        assert module in workflow, module
        assert module in gated, module


def _argument_lines(text):
    return [i for i, line in enumerate(text.split("\n")) if ARGUMENT.match(line)]


def _ordinary_lines(text):
    """Argument lines for tests the real files run whole, not only a node id."""
    return [
        i
        for i, line in enumerate(text.split("\n"))
        if ARGUMENT.match(line)
        and ARGUMENT.match(line).group(1) not in GATED_ONLY
    ]


def _edited(text, which, change, lines_of=None):
    """Copy of text with change(line) applied to the n-th test-path line of the command."""
    lines = text.split("\n")
    index = (lines_of or _argument_lines)(text)[which]
    lines[index] = change(lines[index])
    return "\n".join(lines)


def _gated():
    return GATED.read_text(encoding="utf-8")


def _job():
    return _split_workflow(WORKFLOW.read_text(encoding="utf-8"))[1]


@pytest.mark.parametrize("text", [_gated, _job], ids=["gated", "workflow"])
@pytest.mark.parametrize("which", [0, 5, -1], ids=["first", "middle", "last"])
def test_a_commented_out_argument_fails_the_guard(text, which):
    broken = _edited(text(), which, lambda line: line.replace(line.strip(), "# " + line.strip()))
    with pytest.raises(AssertionError, match="comment inside the pytest argument list"):
        _pytest_arguments(broken)


@pytest.mark.parametrize("text", [_gated, _job], ids=["gated", "workflow"])
def test_an_inline_comment_after_an_argument_fails_the_guard(text):
    broken = _edited(text(), 5, lambda line: line + "  # flaky", _ordinary_lines)
    with pytest.raises(AssertionError, match="comment inside the pytest argument list"):
        _pytest_arguments(broken)


@pytest.mark.parametrize("text", [_gated, _job], ids=["gated", "workflow"])
def test_a_comment_on_the_pytest_line_itself_fails_the_guard(text):
    broken = text().replace("python -m pytest -q \\", "python -m pytest -q  # slice \\", 1)
    assert broken != text()
    with pytest.raises(AssertionError, match="no 'python -m pytest -q"):
        _pytest_arguments(broken)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda t: t.replace("python -m pytest -q \\", "python -m pytest -q --co \\", 1),
        lambda t: t.replace("python -m pytest -q \\", "python -m pytest -q -k nothing \\", 1),
        lambda t: t.replace("python -m pytest -q \\", "true || python -m pytest -q \\", 1),
        lambda t: t.replace("python -m pytest -q \\", "echo python -m pytest -q \\", 1),
        lambda t: t.replace("python -m pytest -q \\", "python -m pytest -q ; true \\", 1),
    ],
    ids=["--co", "-k", "true-or", "echo", "semicolon"],
)
@pytest.mark.parametrize("text", [_gated, _job], ids=["gated", "workflow"])
def test_a_flag_or_wrapper_on_the_pytest_line_fails_the_guard(text, mutate):
    broken = mutate(text())
    assert broken != text()
    with pytest.raises(AssertionError):
        _pytest_arguments(broken)


@pytest.mark.parametrize(
    "change",
    [
        lambda line: line.replace(".py", ".py::test_one"),
        lambda line: f'"{line.strip()}"' if not line.rstrip().endswith("\\") else line.replace(line.strip().split()[0], f'"{line.strip().split()[0]}"'),
        lambda line: line.replace("tests/", "--deselect tests/"),
        lambda line: line.replace("tests/", "--ignore=tests/"),
        lambda line: line + " || true",
    ],
    ids=["node-id", "quoted", "--deselect", "--ignore", "or-true"],
)
@pytest.mark.parametrize("text", [_gated, _job], ids=["gated", "workflow"])
def test_an_argument_that_is_not_a_bare_test_path_fails_the_guard(text, change):
    broken = _edited(text(), 5, change, _ordinary_lines)
    assert broken != text()
    with pytest.raises(
        AssertionError, match="unexpected content|narrows a test path"
    ):
        _pytest_arguments(broken)


@pytest.mark.parametrize("text", [_gated, _job], ids=["gated", "workflow"])
def test_a_duplicated_path_fails_the_guard(text):
    lines = text().split("\n")
    ordinary = _ordinary_lines(text())
    lines[ordinary[1]] = lines[ordinary[0]]
    with pytest.raises(AssertionError, match="listed twice"):
        _pytest_arguments("\n".join(lines))


@pytest.mark.parametrize("text", [_gated, _job], ids=["gated", "workflow"])
def test_a_space_after_a_backslash_fails_the_guard(text):
    """Bash does not continue the line, so the rest of the list would not run."""
    broken = _edited(text(), 5, lambda line: line + " ", _ordinary_lines)
    with pytest.raises(AssertionError, match="unexpected content in the pytest argument list"):
        _pytest_arguments(broken)


def test_a_jobs_word_in_a_comment_does_not_confuse_the_split():
    workflow = "# jobs: are defined below\n" + WORKFLOW.read_text(encoding="utf-8")
    triggers, job = _split_workflow(workflow)
    assert "pull_request:" in triggers, "the trigger section must still be the part before jobs:"
    assert "python -m pytest -q" in job and "python -m pytest -q" not in triggers


def test_a_second_pytest_command_line_fails_the_guard():
    job = _job()
    with pytest.raises(AssertionError, match="more than one"):
        _pytest_arguments(job + "\n          python -m pytest -q \\\n            tests/test_x.py\n")


def _missing_files(paths):
    return sorted(p for p in paths if not (ROOT / p).is_file())


def test_every_listed_test_file_exists():
    _, workflow, gated = _selections()
    assert _missing_files(workflow | gated) == []


def test_a_listed_test_file_that_does_not_exist_is_reported():
    assert _missing_files({"tests/test_does_not_exist_zzz.py"}) == ["tests/test_does_not_exist_zzz.py"]


def test_both_triggers_run_on_everything_but_the_docs_only_allowlist():
    """No hand-listed paths: a change outside docs/** and **/*.md runs the gate."""
    triggers, _, _ = _selections()
    assert "paths:" not in triggers, "a paths: allowlist drifts; use paths-ignore"
    assert triggers.count("paths-ignore: &unit1_slice_ignore") == 1
    assert triggers.count("paths-ignore: *unit1_slice_ignore") == 1
    ignored = re.findall(r'^\s*-\s*"([^"]+)"\s*$', triggers, flags=re.MULTILINE)
    assert ignored == ["docs/**", "**/*.md"]


def test_the_real_files_pass_the_strict_command_shape():
    _pytest_arguments(_job())
    _pytest_arguments(_gated())


def test_a_node_id_is_allowed_only_on_the_paths_the_script_narrows_on_purpose():
    gated = _gated()
    narrowed = [
        line for line in gated.split("\n") if ARGUMENT.match(line) and ARGUMENT.match(line).group(2)
    ]
    assert all(ARGUMENT.match(line).group(1) in GATED_ONLY for line in narrowed)
