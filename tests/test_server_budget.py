"""Structural guard, not a behavior test: size and coupling budgets for server.py.

Lower a number when it drops. Never raise one. A PR that legitimately grows server.py, such as #1603,
rebases this file with its own number. See docs/server-refactor-plan.md. Delete the file in R12,
when the final budgets move into tests/test_import_layers.py.
"""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SERVER_LINES = 3489
INTERNAL_IMPORTS_OF_SERVER = 19
TEST_REFERENCES_TO_SERVER_INTERNALS = 231

_IMPORT = re.compile(r"^\s*(from server import|import server\b)", re.M)
_REFERENCE = re.compile(r"\b(?:srv|server)\.(?!app\b|py\b)[A-Za-z_]+")


def _tracked(pattern):
    out = subprocess.run(["git", "ls-files", pattern], cwd=ROOT, capture_output=True, text=True, check=True)
    return [ROOT / line for line in out.stdout.split()]


def test_server_py_does_not_grow():
    assert len((ROOT / "server.py").read_text().splitlines()) <= SERVER_LINES


def test_internal_packages_do_not_gain_imports_of_server():
    count = sum(len(_IMPORT.findall(path.read_text())) for path in _tracked("internal/*.py"))
    assert count <= INTERNAL_IMPORTS_OF_SERVER


def test_tests_do_not_gain_references_to_server_internals():
    count = sum(len(_REFERENCE.findall(path.read_text())) for path in _tracked("tests/*.py") if path.name != "test_server_budget.py")
    assert count <= TEST_REFERENCES_TO_SERVER_INTERNALS
