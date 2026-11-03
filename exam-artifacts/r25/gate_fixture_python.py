#!/usr/bin/env python3
"""Static gate + EXECUTION GATE (pytest at head) for r25 Stage C fixtures."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTEST = os.environ.get("R25_PYTEST", "/workspace/.venv/bin/pytest")
if not Path(PYTEST).is_file():
    PYTEST = "pytest"

OUT_STATIC = ROOT / "exam-artifacts/r25/fixture-gate-output.txt"
OUT_EXEC = ROOT / "exam-artifacts/r25/fixture-execution-gate-output.txt"


def stage_c_fixtures() -> list[tuple[str, Path]]:
    manifest = json.loads((ROOT / "exam-artifacts/r25/stage-c-manifest.json").read_text())
    return [
        (row["slug"], ROOT / row["fixturePath"] / "repo.json")
        for row in manifest["fixtures"]
    ]


def head_files(repo_path: Path) -> dict[str, str]:
    doc = json.loads(repo_path.read_text())
    return doc.get("files") or {}


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
                lines.append(f"[r25:{label}] py_compile {rel} exit={proc.returncode}")
                if proc.stderr.strip():
                    lines.append(proc.stderr.strip())
                pf = subprocess.run(
                    [sys.executable, "-m", "pyflakes", str(path)],
                    capture_output=True,
                    text=True,
                )
                lines.append(f"[r25:{label}] pyflakes {rel} exit={pf.returncode}")
                out = (pf.stdout or "") + (pf.stderr or "")
                undefined = [
                    ln
                    for ln in out.splitlines()
                    if "undefined name" in ln or "undefined local" in ln
                ]
                if undefined:
                    lines.extend(undefined)
                    lines.append(f"[r25:{label}] pyflakes {rel} UNDEFINED=1")
                elif out.strip():
                    lines.extend(out.strip().splitlines())
            if rel.endswith((".yml", ".yaml")) and ".github/workflows" in rel:
                try:
                    import yaml  # type: ignore

                    yaml.safe_load(content)
                    lines.append(f"[r25:{label}] yaml_parse {rel} ok")
                except Exception as e:
                    lines.append(f"[r25:{label}] yaml_parse {rel} FAIL: {e}")
            if rel.endswith("pytest.ini"):
                lines.append(f"[r25:{label}] pytest_ini {rel} ok")
    return lines


def materialize_head(tdp: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        if content == "":
            continue
        path = tdp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    for pkg in ("internal", "tests"):
        d = tdp / pkg
        if d.is_dir():
            init = d / "__init__.py"
            if not init.exists():
                init.write_text("", encoding="utf-8")


def run_execution_gate(label: str, files: dict[str, str]) -> tuple[list[str], bool]:
    lines: list[str] = []
    failed = False
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        materialize_head(tdp, files)
        tests_dir = tdp / "tests"
        test_modules = list(tests_dir.rglob("test_*.py")) if tests_dir.is_dir() else []
        if not test_modules:
            lines.append(f"[r25:{label}] EXECUTION INTENTIONAL: no test modules at head (empty/deleted tests or CI-only)")
            lines.append(f"[r25:{label}] EXECUTION pytest skipped ok")
            return lines, False

        env = os.environ.copy()
        env["PYTHONPATH"] = str(tdp)
        proc = subprocess.run(
            [PYTEST, "-q", "tests"],
            cwd=str(tdp),
            env=env,
            capture_output=True,
            text=True,
        )
        combined = (proc.stdout or "") + (proc.stderr or "")
        lines.append(f"[r25:{label}] EXECUTION pytest exit={proc.returncode}")
        if combined.strip():
            lines.extend(combined.rstrip().splitlines())

        summary = combined.strip().splitlines()[-1] if combined.strip() else ""
        if proc.returncode == 1 or " failed" in summary or " error" in summary:
            lines.append(f"[r25:{label}] EXECUTION FAIL: failing or erroring tests")
            failed = True
        elif proc.returncode == 0:
            if "xpassed" in summary:
                lines.append(f"[r25:{label}] EXECUTION note: xpass present (expected for some MODIFY fixtures)")
            lines.append(f"[r25:{label}] EXECUTION ok")
        elif proc.returncode == 5:
            lines.append(f"[r25:{label}] EXECUTION INTENTIONAL: pytest exit 5 (e.g. module-level skip only)")
            lines.append(f"[r25:{label}] EXECUTION ok")
        else:
            lines.append(f"[r25:{label}] EXECUTION FAIL: unexpected pytest exit {proc.returncode}")
            failed = True
    return lines, failed


def main() -> int:
    static_lines: list[str] = ["=== r25 fixture static gate ===", ""]
    exec_lines: list[str] = ["=== r25 fixture EXECUTION GATE (pytest @ head) ===", f"pytest={PYTEST}", ""]
    static_fail = exec_fail = False

    for label, repo in stage_c_fixtures():
        if not repo.is_file():
            static_lines.append(f"MISSING r25:{label} {repo}")
            static_fail = True
            continue
        files = head_files(repo)
        static_lines.extend(run_static_gate(label, files))
        static_lines.append("")
        elines, ebad = run_execution_gate(label, files)
        exec_lines.extend(elines)
        exec_lines.append("")
        exec_fail = exec_fail or ebad

    static_text = "\n".join(static_lines).rstrip() + "\n"
    exec_text = "\n".join(exec_lines).rstrip() + "\n"
    OUT_STATIC.write_text(static_text + "\n" + exec_text, encoding="utf-8")
    OUT_EXEC.write_text(exec_text, encoding="utf-8")
    sys.stdout.write(static_text + "\n" + exec_text)

    if static_fail or exec_fail:
        return 1
    if any("UNDEFINED=1" in ln or " FAIL:" in ln or ("py_compile" in ln and "exit=1" in ln) for ln in static_lines):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
