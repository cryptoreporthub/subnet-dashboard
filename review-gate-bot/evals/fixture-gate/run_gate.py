#!/usr/bin/env python3
"""Fail-closed fixture gate (R0.2): one entrypoint over all fixtures."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BOT = Path(__file__).resolve().parents[2]
REPO = BOT.parents[0]
GATE = BOT / "evals/fixture-gate"

# Import after path setup when run as script
sys.path.insert(0, str(GATE))
from gate_core import resolve_gate_python  # noqa: E402


def run(cmd: list[str], *, cwd: Path | None = None, env: dict | None = None) -> int:
    proc = subprocess.run(cmd, cwd=str(cwd or REPO), env=env, text=True)
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    return proc.returncode


def main() -> int:
    py, exec_errors = resolve_gate_python(REPO, bootstrap=True)
    if exec_errors:
        print("fixture-gate FAILED: executor unavailable", flush=True)
        for line in exec_errors:
            print(f"  {line}", flush=True)
        return 1

    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(REPO))
    env["ORACLE_PYTHON"] = py

    steps: list[tuple[str, list[str], Path]] = [
        ("gate executor probe", [py, "-m", "pytest", "-q", str(GATE / "test_gate_executor.py")], REPO),
        ("structural pytest", [py, "-m", "pytest", "-q", str(GATE / "test_gate.py")], REPO),
        ("known-bad rejection", [py, "-m", "pytest", "-q", str(GATE / "test_known_bad.py")], REPO),
        ("pack B author-voice + exam-dup gate", [py, "-m", "pytest", "-q", str(GATE / "test_pack_b_gate.py")], REPO),
        (
            "oracle-gen --check (executed oracle ON; ORACLE_PYTHON=%s)" % py,
            [py, "evals/oracle-gen/gen.py", "--check", "--python", py],
            BOT,
        ),
    ]

    r27_gate = REPO / "exam-artifacts/r27/gate_fixture_python.py"
    if r27_gate.is_file():
        steps.append(
            (
                "r27 stage-C workflow execution gate",
                [py, str(r27_gate)],
                REPO,
            )
        )

    failed = False
    for label, cmd, cwd in steps:
        print(f"\n=== fixture-gate: {label} ===", flush=True)
        code = run(cmd, cwd=cwd, env=env)
        if code != 0:
            print(f"fixture-gate FAILED at: {label} (exit {code})", flush=True)
            failed = True
            break
        print(f"fixture-gate ok: {label}", flush=True)

    if failed:
        return 1
    print(f"\nfixture-gate: all steps ok (gate python={py})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
