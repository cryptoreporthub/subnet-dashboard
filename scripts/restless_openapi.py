#!/usr/bin/env python3
"""Keep .restless/openapi.json aligned with FastAPI server:app.openapi()."""
from __future__ import annotations

import argparse
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPENAPI_PATH = os.path.join(REPO_ROOT, ".restless", "openapi.json")


def _live_spec() -> dict:
    os.environ.setdefault("DISABLE_BACKGROUND_SCANS", "1")
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)
    from server import app

    return app.openapi()


def _load_committed() -> dict:
    with open(OPENAPI_PATH, encoding="utf-8") as f:
        return json.load(f)


def _serialize(spec: dict) -> str:
    return (
        json.dumps(spec, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
        + "\n"
    )


def cmd_check() -> int:
    live = _live_spec()
    committed = _load_committed()
    if live == committed:
        print(f"✓ {OPENAPI_PATH} matches server:app.openapi()")
        return 0
    print(
        f"✗ {OPENAPI_PATH} is out of date — run: "
        "DISABLE_BACKGROUND_SCANS=1 python scripts/restless_openapi.py --write",
        file=sys.stderr,
    )
    return 1


def cmd_write() -> int:
    spec = _live_spec()
    os.makedirs(os.path.dirname(OPENAPI_PATH), exist_ok=True)
    with open(OPENAPI_PATH, "w", encoding="utf-8") as f:
        f.write(_serialize(spec))
    print(f"✓ wrote {OPENAPI_PATH}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Regenerate .restless/openapi.json from the live app",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if committed spec differs from app.openapi() (default)",
    )
    args = parser.parse_args()
    if args.write and args.check:
        print("Use only one of --write or --check", file=sys.stderr)
        return 2
    if args.write:
        return cmd_write()
    return cmd_check()


if __name__ == "__main__":
    raise SystemExit(main())
