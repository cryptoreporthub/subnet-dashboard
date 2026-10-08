"""Heavy-job gate INFO lines must reach stdout under the app's logging setup."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_heavy_job_gate_info_reaches_stdout_after_app_boot():
    code = (
        "import logging\n"
        "import internal.worker  # boot path that configures app logging\n"
        "from internal.heavy_job_gate import heavy_job_slot\n"
        "assert logging.getLogger('internal.council.resolver_scheduler').isEnabledFor(logging.INFO)\n"
        "with heavy_job_slot('probe'):\n"
        "    pass\n"
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert "heavy_job_slot acquire name=probe" in out.stdout
    assert "heavy_job_slot release name=probe" in out.stdout
