"""Real launcher / spawn isolation for snapshot guard."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


def test_run_web_with_guard_import_does_not_install_guard():
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "run_web_with_guard.py"
    spec = importlib.util.spec_from_file_location("run_web_with_guard_import_test", script)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    import internal.snapshot_guard as guard

    assert guard._ORIG is None


def test_spawn_fetch_child_from_web_process_tree():
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, str(root / "tests" / "spawn_fetch_from_web_main.py")],
        cwd=root,
        env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": str(root)},
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
