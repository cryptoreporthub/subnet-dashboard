"""Subprocess helper: run scripts/run_web_with_guard.py as __main__ like Fly spawn."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from unittest.mock import patch


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.environ["LIVE_SUBNETS_FETCH_CHILD"] = "1"
    script = root / "scripts" / "run_web_with_guard.py"
    with patch("uvicorn.run"):
        import runpy

        runpy.run_path(str(script), run_name="__main__")
    import internal.snapshot_guard as guard

    if guard._ORIG is not None:
        raise SystemExit(2)
    if any(t.name == "learning-snapshot-prewarm" for t in threading.enumerate()):
        raise SystemExit(3)
    if "internal.learning.routes" in sys.modules:
        raise SystemExit(4)


if __name__ == "__main__":
    main()
