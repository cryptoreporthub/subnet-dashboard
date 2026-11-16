"""CLI entry: python -m tools.reviewer_scorecard.cli <tables_dir> [out_dir]."""

from __future__ import annotations

import sys
from pathlib import Path

from tools.reviewer_scorecard.generator import generate_from_directory


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: python -m tools.reviewer_scorecard.cli <tables_dir> [out_dir]", file=sys.stderr)
        return 2
    table_dir = Path(argv[0])
    out_dir = Path(argv[1]) if len(argv) > 1 else table_dir.parent / "generated"
    generate_from_directory(table_dir, out_dir)
    print(f"wrote scorecard to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
