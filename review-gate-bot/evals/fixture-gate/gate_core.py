"""Reusable checks for fixture gate + known-bad profiles."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TAUTOLOGY = re.compile(r"assert\s+True\b")
BARE_PYTEST = re.compile(r"^\s*-\s*run:\s*pytest\s", re.M)


class GateExecutorError(RuntimeError):
    """Fail-closed: pytest executor (python + pytest + pytest-shard) unavailable."""


def _python_candidates(repo_root: Path) -> list[str]:
    out: list[str] = []
    venv = repo_root / ".venv/bin/python"
    if venv.is_file():
        out.append(str(venv))
    for name in (sys.executable, shutil.which("python3"), shutil.which("python")):
        if name and name not in out:
            out.append(name)
    return out


def executor_probe(python: str) -> list[str]:
    """Return human-readable defects; empty list means OK for shard workflow checks."""
    problems: list[str] = []
    if not python or not Path(python).exists():
        return ["python interpreter not found"]
    ver = subprocess.run([python, "-m", "pytest", "--version"], capture_output=True, text=True)
    if ver.returncode != 0:
        problems.append(f"pytest not runnable via {python!r} (-m pytest --version exit {ver.returncode})")
    shard = subprocess.run(
        [python, "-c", "import pytest_shard"],
        capture_output=True,
        text=True,
    )
    if shard.returncode != 0:
        problems.append(f"pytest-shard plugin missing for {python!r} (import pytest_shard failed)")
    return problems


def _gate_pytest_venv_dir() -> Path:
    return Path(__file__).resolve().parent / ".gate-pytest-venv"


def bootstrap_pytest(python: str) -> tuple[str, list[str]]:
    """Install pytest + pytest-shard for gate runs (clean checkout, no repo .venv).

    Uses a dedicated venv beside gate_core.py so PEP-668 system Pythons do not block pip.
    Returns (python_to_use, probe_errors).
    """
    venv_dir = _gate_pytest_venv_dir()
    venv_py = venv_dir / "bin" / "python"
    if not venv_py.is_file():
        venv_dir.parent.mkdir(parents=True, exist_ok=True)
        created = subprocess.run([python, "-m", "venv", str(venv_dir)], capture_output=True, text=True)
        if created.returncode != 0:
            tail = (created.stderr or created.stdout or "")[-400:]
            return python, [f"python -m venv failed for gate executor: {tail}"]
    target = str(venv_py if venv_py.is_file() else python)
    proc = subprocess.run(
        [target, "-m", "pip", "install", "pytest", "pytest-shard", "-q"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-400:]
        return target, [f"pip install pytest pytest-shard failed: {tail}"]
    return target, executor_probe(target)


def bootstrap_oracle_deps(python: str, repo_root: Path) -> list[str]:
    """App deps for oracle-gen executed behavior (subnet_universe pytest in archive tree)."""
    req = repo_root / "requirements.txt"
    if not req.is_file():
        return []
    proc = subprocess.run(
        [python, "-m", "pip", "install", "-r", str(req), "-q"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-400:]
        return [f"pip install -r requirements.txt for oracle failed: {tail}"]
    return []


def resolve_gate_python(repo_root: Path, *, bootstrap: bool = True) -> tuple[str, list[str]]:
    """Locate a python that can run `python -m pytest` with pytest-shard. Fail-closed errors if none."""
    for py in _python_candidates(repo_root):
        problems = executor_probe(py)
        if not problems:
            return py, []
    if not bootstrap:
        return "", ["executor unavailable: no python with pytest and pytest-shard on PATH"]
    base = _python_candidates(repo_root)[0] if _python_candidates(repo_root) else sys.executable
    py, problems = bootstrap_pytest(base)
    if problems:
        return py, [f"executor unavailable: {p}" for p in problems]
    if str(_gate_pytest_venv_dir()) in py:
        dep_errors = bootstrap_oracle_deps(py, repo_root)
        if dep_errors:
            return py, [f"executor unavailable: {e}" for e in dep_errors]
    return py, []


def require_gate_python(repo_root: Path) -> str:
    py, errors = resolve_gate_python(repo_root)
    if errors:
        raise GateExecutorError("; ".join(errors))
    return py


def repo_files(repo_doc: dict) -> dict[str, str]:
    return repo_doc.get("files") or {}


def check_no_tautology_on_pass(repo_doc: dict, oracle: str) -> list[str]:
    if oracle != "PASS":
        return []
    errors: list[str] = []
    for path, content in repo_files(repo_doc).items():
        if not path.endswith(".py") or "test_" not in path:
            continue
        if TAUTOLOGY.search(content or ""):
            errors.append(f"tautology assert True in PASS fixture: {path}")
    return errors


def check_ci_pytest_invocation(repo_doc: dict) -> list[str]:
    errors: list[str] = []
    for path, content in repo_files(repo_doc).items():
        if ".github/workflows" not in path or not path.endswith((".yml", ".yaml")):
            continue
        if not content:
            continue
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("- run: pytest") or stripped.startswith("- run: pytest "):
                errors.append(f"bare pytest in workflow (need python -m pytest): {path}: {stripped}")
    return errors


def check_label_weight_assertion(repo_doc: dict) -> list[str]:
    """Wrong expected constant (729 vs measured 629 for legacy label)."""
    errors: list[str] = []
    prod = repo_files(repo_doc).get("internal/r25_label_weight.py") or ""
    if "label_weight" not in prod:
        return errors
    for path, content in repo_files(repo_doc).items():
        if not path.endswith(".py"):
            continue
        if re.search(r'label_weight\(["\']legacy["\']\)\s*==\s*729', content or ""):
            errors.append(f"wrong label_weight legacy expected 729 (should be 629): {path}")
    return errors


def check_r25_p6_behavior(repo_doc: dict) -> list[str]:
    """Production behavior changed vs base but tests emptied."""
    files = repo_files(repo_doc)
    base = repo_doc.get("baseFiles") or {}
    head_impl = files.get("internal/r25_feature_flags.py") or ""
    base_impl = base.get("internal/r25_feature_flags.py") or ""
    head_test = files.get("tests/test_r25_feature_flags.py") or ""
    base_test = base.get("tests/test_r25_feature_flags.py") or ""
    if not head_impl or not base_impl:
        return []
    if head_impl.strip() == base_impl.strip():
        return []
    if base_test.strip() and not head_test.strip():
        return ["r25-p6: production changed but head tests removed/empty vs base"]
    if "return True" in head_impl and "ENABLE_LEGACY_FOO" in base_impl and not head_test.strip():
        return ["r25-p6: refresh_enabled pinned True without tests"]
    return []


def check_shard_collects_nothing(repo_doc: dict, python: str) -> list[str]:
    files = repo_files(repo_doc)
    steps = []
    for path, content in files.items():
        if ".github/workflows" not in path:
            continue
        for line in (content or "").splitlines():
            if line.strip().startswith("- run:") and "pytest" in line:
                steps.append(line.strip().split("run:", 1)[1].strip())
    if not steps:
        return []
    shard_steps = [s for s in steps if "pytest-shard" in s or "--shard-id" in s]
    if not shard_steps:
        return []
    exec_errors = executor_probe(python)
    if exec_errors:
        return [f"executor unavailable: {exec_errors[0]}"]
    errors: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        for rel, content in files.items():
            if content == "":
                continue
            path = tdp / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        env = {"PATH": str(Path(python).parent) + ":" + os.environ.get("PATH", "")}
        for raw in steps:
            cmd = raw.replace("${{ matrix.shard-index }}", "1").replace("${{matrix.shard-index}}", "1")
            if "pytest-shard" not in cmd and "--shard-id" not in cmd:
                continue
            proc = subprocess.run(
                cmd,
                cwd=str(tdp),
                shell=True,
                capture_output=True,
                text=True,
                env=env,
            )
            combined = (proc.stdout or "") + (proc.stderr or "")
            if proc.returncode == 5 or "no tests ran" in combined.lower():
                errors.append(f"shard matrix index 1 collects nothing: exit={proc.returncode}")
    return errors


def check_planted_oracle_semantics(oracle_doc: dict) -> list[str]:
    """Planted-bug fixtures must not claim PASS when the planted head still exhibits the bug."""
    fixture = oracle_doc.get("fixture") or ""
    behavior = oracle_doc.get("behavior") or {}
    expected = behavior.get("expectedVerdict")
    if expected != "PASS":
        return []
    if fixture == "hard-planted-blank-reload":
        planted = behavior.get("planted") or {}
        reader = planted.get("reader") or {}
        if reader.get("servingNetuids") == 0 and reader.get("keptLastComplete") is False:
            return ["planted-blank-reload oracle must not expect PASS at planted head"]
    return []


def validate_oracle_json(oracle_doc: dict) -> list[str]:
    return check_planted_oracle_semantics(oracle_doc)


DEFECT_VOICE = re.compile(
    r"\b(omit|drop|without|ignores|skip|shrink|bypass|disable|relax|untested|claimed)\b",
    re.I,
)


PR_SNAPSHOT_KEYS = frozenset({"number", "headSha", "baseSha", "draft", "title", "files", "url"})
GATE_STATE_KEYS = frozenset(
    {"headSha", "mc", "cursor", "ditto", "replit", "suite", "replitTagged", "next", "suiteDetail"}
)


def check_fixture_snapshot_keys(dirname: str, pr: dict, gate: dict) -> list[str]:
    """Pack B / eval fixtures must not add keys the production gate tool never returns."""
    errors: list[str] = []
    extra_pr = set(pr) - PR_SNAPSHOT_KEYS
    extra_gate = set(gate) - GATE_STATE_KEYS
    if extra_pr:
        errors.append(f"{dirname}: pr.json extra keys {sorted(extra_pr)}")
    if extra_gate:
        errors.append(f"{dirname}: gate.json extra keys {sorted(extra_gate)}")
    return errors


def pack_b_control(dirname: str, gate: dict) -> bool:
    return dirname.startswith("r1b-f3-ctrl-")


def author_voice_text(pr: dict, gate: dict) -> str:
    return pr.get("title") or ""


def check_r1b_author_voice(dirname: str, pr: dict, gate: dict) -> list[str]:
    if not dirname.startswith("r1b-"):
        return []
    if pack_b_control(dirname, gate):
        return []
    if DEFECT_VOICE.search(author_voice_text(pr, gate)):
        return [f"{dirname}: defect-naming token in title (author voice)"]
    return []


def diff_patch_fingerprint(diff: dict) -> str:
    import hashlib

    parts = [f["patch"] for f in sorted(diff.get("files") or [], key=lambda x: x.get("path", ""))]
    return hashlib.sha256("\n---\n".join(parts).encode()).hexdigest()


def exam_patch_fingerprints(fixtures_root: Path) -> set[str]:
    fps: set[str] = set()
    if not fixtures_root.is_dir():
        return fps
    for d in fixtures_root.iterdir():
        if not d.is_dir() or not d.name.startswith("hard-"):
            continue
        if d.name.startswith("hard-r24-"):
            continue
        diff_path = d / "diff.json"
        if diff_path.is_file():
            fps.add(diff_patch_fingerprint(json.loads(diff_path.read_text())))
    return fps


def check_r1b_exam_duplicate(dirname: str, diff: dict, exam_fps: set[str]) -> list[str]:
    if not dirname.startswith("r1b-"):
        return []
    if diff_patch_fingerprint(diff) in exam_fps:
        return [f"{dirname}: unified diff matches an exam (hard-*) fixture patch"]
    return []


def f3_visible_haystack(pr: dict, diff: dict) -> str:
    title = pr.get("title") or ""
    patches = "\n".join((f.get("patch") or "") for f in diff.get("files") or [])
    return f"{title}\n{patches}"


def check_f3_visible_claim(dirname: str, pr: dict, diff: dict, oracle_doc: dict) -> list[str]:
    if not dirname.startswith("r1b-f3-") or dirname.startswith("r1b-f3-ctrl-"):
        return []
    behavior = oracle_doc.get("behavior") or {}
    claim = behavior.get("visibleClaim")
    if not claim:
        return []
    if claim not in f3_visible_haystack(pr, diff):
        return [f"{dirname}: visibleClaim not verbatim in PR title or diff"]
    return []


def validate_r1b_fixture_dir(fixture_dir: Path, *, exam_fps: set[str] | None = None) -> list[str]:
    name = fixture_dir.name
    if not name.startswith("r1b-"):
        return []
    errors: list[str] = []
    pr = json.loads((fixture_dir / "pr.json").read_text())
    gate = json.loads((fixture_dir / "gate.json").read_text())
    diff = json.loads((fixture_dir / "diff.json").read_text())
    errors.extend(check_fixture_snapshot_keys(name, pr, gate))
    errors.extend(check_r1b_author_voice(name, pr, gate))
    fps = exam_fps if exam_fps is not None else exam_patch_fingerprints(fixture_dir.parent)
    errors.extend(check_r1b_exam_duplicate(name, diff, fps))
    oracle_path = fixture_dir / "oracle.json"
    if oracle_path.is_file():
        oracle_doc = json.loads(oracle_path.read_text())
        errors.extend(check_f3_visible_claim(name, pr, diff, oracle_doc))
    return errors


def validate_repo_doc(repo_doc: dict, *, python: str) -> list[str]:
    oracle = (repo_doc.get("oracle") or "MODIFY") if isinstance(repo_doc.get("oracle"), str) else "MODIFY"
    if isinstance(repo_doc.get("gate"), dict):
        oracle = repo_doc["gate"].get("oracle") or oracle
    errors: list[str] = []
    errors.extend(check_no_tautology_on_pass(repo_doc, oracle))
    errors.extend(check_ci_pytest_invocation(repo_doc))
    errors.extend(check_label_weight_assertion(repo_doc))
    errors.extend(check_r25_p6_behavior(repo_doc))
    errors.extend(check_shard_collects_nothing(repo_doc, python))
    return errors


def git_show(repo_root: Path, rev: str, path: str) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "show", f"{rev}:{path}"],
        capture_output=True,
        text=True,
    )
    return proc.stdout if proc.returncode == 0 else None


def historical_rejection(
    repo_root: Path,
    rev: str,
    path: str,
    label: str,
    doc: dict,
    *,
    python: str,
) -> list[str]:
    """Rules that must fire on known-bad snapshots from git history (R0.2 acceptance)."""
    exec_errors = executor_probe(python)
    if exec_errors:
        return [f"executor unavailable: {exec_errors[0]}"]
    errors: list[str] = []
    errors.extend(validate_repo_doc(doc, python=python))
    files = repo_files(doc)
    if "consolidation-v1" in label or (
        rev.startswith("8ac92798") and "consolidation-drops-coverage/repo" in path
    ):
        head = files.get("tests/test_subnet_universe.py") or ""
        if "test_edge_combined" in head and TAUTOLOGY.search(head):
            errors.append("r24 consolidation-v1: merged edge tests collapsed to assert True")
    if "removal-guarded-b assert True" in label or (
        rev.startswith("8ac92798") and "removal-guarded-b/repo" in path and "v2" not in path
    ):
        head = files.get("tests/test_subnet_universe.py") or ""
        base = (doc.get("baseFiles") or {}).get("tests/test_subnet_universe.py") or ""
        if head.count("assert True") >= 3:
            errors.append("r24 removal-guarded-b v1: bulk placeholder tests are tautologies")
        elif not head.strip() and base.count("assert True") >= 3:
            errors.append("r24 removal-guarded-b v1: base tests are tautologies with empty head tests")
    return errors


def load_repo_json_at(repo_root: Path, rev: str, path: str) -> dict | None:
    raw = git_show(repo_root, rev, path)
    if not raw:
        return None
    return json.loads(raw)
