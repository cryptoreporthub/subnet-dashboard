#!/usr/bin/env python3
"""Static gate + EXECUTION GATE (exact workflow run steps @ repo root, no PYTHONPATH)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENV_PYTHON = os.environ.get(
    "R27_VENV_PYTHON",
    "/workspace/.venv/bin/python" if Path("/workspace/.venv/bin/python").is_file() else sys.executable,
)
VENV_BIN = str(Path(VENV_PYTHON).parent)

OUT_STATIC = ROOT / "exam-artifacts/r27/fixture-gate-output.txt"
OUT_EXEC = ROOT / "exam-artifacts/r27/fixture-execution-gate-output.txt"


def stage_c_fixtures() -> list[tuple[str, Path]]:
    manifest = json.loads((ROOT / "exam-artifacts/r27/stage-c-manifest.json").read_text())
    return [
        (row["slug"], ROOT / row["fixturePath"] / "repo.json")
        for row in manifest["fixtures"]
    ]


def head_files(repo_path: Path) -> dict[str, str]:
    doc = json.loads(repo_path.read_text())
    return doc.get("files") or {}


def workflow_run_steps(files: dict[str, str]) -> list[str]:
    steps: list[str] = []
    for path in sorted(files):
        if ".github/workflows" not in path or not path.endswith((".yml", ".yaml")):
            continue
        content = files[path]
        if not content:
            continue
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("- run:"):
                steps.append(stripped.split("run:", 1)[1].strip())
    return steps


def run_static_gate(label: str, files: dict[str, str]) -> list[str]:
    lines: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        for rel, content in sorted(files.items()):
            if content == "":
                continue
            path = tdp / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            if rel.endswith(".py"):
                proc = subprocess.run(
                    [sys.executable, "-m", "py_compile", str(path)],
                    capture_output=True,
                    text=True,
                )
                lines.append(f"[r27:{label}] py_compile {rel} exit={proc.returncode}")
                if proc.stderr.strip():
                    lines.append(proc.stderr.strip())
                pf = subprocess.run(
                    [sys.executable, "-m", "pyflakes", str(path)],
                    capture_output=True,
                    text=True,
                )
                lines.append(f"[r27:{label}] pyflakes {rel} exit={pf.returncode}")
                out = (pf.stdout or "") + (pf.stderr or "")
                undefined = [
                    ln
                    for ln in out.splitlines()
                    if "undefined name" in ln or "undefined local" in ln
                ]
                if undefined:
                    lines.extend(undefined)
                    lines.append(f"[r27:{label}] pyflakes {rel} UNDEFINED=1")
                elif out.strip():
                    lines.extend(out.strip().splitlines())
            if rel.endswith((".yml", ".yaml")) and ".github/workflows" in rel:
                try:
                    import yaml  # type: ignore

                    yaml.safe_load(content)
                    lines.append(f"[r27:{label}] yaml_parse {rel} ok")
                except Exception as e:
                    lines.append(f"[r27:{label}] yaml_parse {rel} FAIL: {e}")
            if rel.endswith("pytest.ini"):
                lines.append(f"[r27:{label}] pytest_ini {rel} ok")
    return lines


def materialize_head(tdp: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        if content == "":
            continue
        path = tdp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def sanitize_workflow_cmd(cmd: str) -> str:
    """Local execution: expand GH Actions matrix; shard flags need plugin (ponytail: fall back to module pytest)."""
    cmd = (
        cmd.replace("${{ matrix.shard-index }}", "0")
        .replace("${{matrix.shard-index}}", "0")
    )
    if "--shard-id" in cmd or "--num-shards" in cmd:
        # ponytail: gate venv has no pytest-shard; run full suite like CI would on one shard
        return f"{VENV_PYTHON} -m pytest -q tests"
    if cmd.strip() == "pytest -q":
        return f"{VENV_PYTHON} -m pytest -q tests"
    return cmd


def run_execution_gate(label: str, files: dict[str, str]) -> tuple[list[str], bool]:
    lines: list[str] = []
    failed = False
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        materialize_head(tdp, files)
        tests_dir = tdp / "tests"
        test_modules = list(tests_dir.rglob("test_*.py")) if tests_dir.is_dir() else []
        run_steps = workflow_run_steps(files)

        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env["PATH"] = f"{VENV_BIN}:{env.get('PATH', '')}"

        if run_steps:
            for cmd in run_steps:
                cmd = sanitize_workflow_cmd(cmd)
                lines.append(f"[r27:{label}] EXECUTION workflow run: {cmd}")
                proc = subprocess.run(
                    cmd,
                    cwd=str(tdp),
                    env=env,
                    shell=True,
                    capture_output=True,
                    text=True,
                )
                combined = (proc.stdout or "") + (proc.stderr or "")
                lines.append(f"[r27:{label}] EXECUTION exit={proc.returncode}")
                if combined.strip():
                    lines.extend(combined.rstrip().splitlines())
                if proc.returncode != 0:
                    if proc.returncode in (4, 5) and not test_modules and "pytest" in cmd:
                        lines.append(
                            f"[r27:{label}] EXECUTION INTENTIONAL: CI workflow only (no tests/ at head)"
                        )
                        continue
                    lines.append(f"[r27:{label}] EXECUTION FAIL: workflow command failed")
                    failed = True
                    break
            if not failed:
                lines.append(f"[r27:{label}] EXECUTION ok")
            return lines, failed

        if not test_modules:
            lines.append(
                f"[r27:{label}] EXECUTION INTENTIONAL: no test modules at head (empty/deleted tests or CI-only)"
            )
            lines.append(f"[r27:{label}] EXECUTION skipped ok")
            return lines, False

        cmd = f"{VENV_PYTHON} -m pytest -q tests"
        lines.append(f"[r27:{label}] EXECUTION (no workflow run steps): {cmd}")
        proc = subprocess.run(
            cmd,
            cwd=str(tdp),
            env=env,
            shell=True,
            capture_output=True,
            text=True,
        )
        combined = (proc.stdout or "") + (proc.stderr or "")
        lines.append(f"[r27:{label}] EXECUTION exit={proc.returncode}")
        if combined.strip():
            lines.extend(combined.rstrip().splitlines())
        summary = combined.strip().splitlines()[-1] if combined.strip() else ""
        if proc.returncode == 1 or " failed" in summary or " error" in summary:
            lines.append(f"[r27:{label}] EXECUTION FAIL: failing or erroring tests")
            failed = True
        elif proc.returncode == 0:
            if "xpassed" in summary:
                lines.append(f"[r27:{label}] EXECUTION note: xpass present (expected for some MODIFY fixtures)")
            lines.append(f"[r27:{label}] EXECUTION ok")
        elif proc.returncode == 5:
            lines.append(f"[r27:{label}] EXECUTION INTENTIONAL: pytest exit 5 (e.g. module-level skip only)")
            lines.append(f"[r27:{label}] EXECUTION ok")
        else:
            lines.append(f"[r27:{label}] EXECUTION FAIL: unexpected pytest exit {proc.returncode}")
            failed = True
    return lines, failed


def main() -> int:
    static_lines: list[str] = ["=== r27 fixture static gate ===", ""]
    exec_lines: list[str] = [
        "=== r27 fixture EXECUTION GATE (exact workflow run steps, repo root, no PYTHONPATH) ===",
        f"venv_python={VENV_PYTHON}",
        "",
    ]
    static_fail = exec_fail = False
    count = 0

    for label, repo in stage_c_fixtures():
        count += 1
        if not repo.is_file():
            static_lines.append(f"MISSING r27:{label} {repo}")
            static_fail = True
            continue
        files = head_files(repo)
        static_lines.extend(run_static_gate(label, files))
        static_lines.append("")
        elines, ebad = run_execution_gate(label, files)
        exec_lines.extend(elines)
        exec_lines.append("")
        exec_fail = exec_fail or ebad

    exec_lines.insert(1, f"fixtures={count} (expect 24)")
    static_text = "\n".join(static_lines).rstrip() + "\n"
    exec_text = "\n".join(exec_lines).rstrip() + "\n"
    OUT_STATIC.write_text(static_text + "\n" + exec_text, encoding="utf-8")
    OUT_EXEC.write_text(exec_text, encoding="utf-8")
    sys.stdout.write(static_text + "\n" + exec_text)

    if count != 24:
        return 1
    if static_fail or exec_fail:
        return 1
    if any("UNDEFINED=1" in ln or " FAIL:" in ln or ("py_compile" in ln and "exit=1" in ln) for ln in static_lines):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
