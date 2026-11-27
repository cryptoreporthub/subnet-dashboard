"""Guard: ci-smoke.yml PR trigger and permissions match issue #1624 PR 0."""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci-smoke.yml"


def _pull_request_section(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    in_pr = False
    for line in lines:
        if re.match(r"^  pull_request:\s*$", line):
            in_pr = True
            continue
        if in_pr:
            if re.match(r"^  \w", line) and not line.startswith("    "):
                break
            out.append(line)
    assert in_pr, "pull_request trigger missing"
    return "\n".join(out)


def test_ci_smoke_pull_request_has_no_branches_filter():
    section = _pull_request_section(WORKFLOW.read_text(encoding="utf-8"))
    assert "branches:" not in section


def test_ci_smoke_pull_request_types_include_edited():
    section = _pull_request_section(WORKFLOW.read_text(encoding="utf-8"))
    assert re.search(r"types:\s*\[.*edited", section)


def test_ci_smoke_declares_contents_read_permission():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"^permissions:\s*$", text, re.M)
    perm_idx = text.index("permissions:")
    jobs_idx = text.index("jobs:")
    assert perm_idx < jobs_idx
    perm_block = text[perm_idx:jobs_idx]
    assert re.search(r"contents:\s*read", perm_block)