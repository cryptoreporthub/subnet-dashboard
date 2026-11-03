#!/usr/bin/env python3
"""SHA-256 manifest for Stage B fixture dirs + blind packs + stage-b-manifest.json."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
R24 = ROOT / "exam-artifacts/r24"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    out: dict[str, str] = {}
    for path in sorted(R24.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("exam-artifacts/r24/fixtures/stage-b/") or (
            rel.startswith("exam-artifacts/r24/blind/b") and rel.endswith(".md")
        ):
            out[rel] = sha256_file(path)
    manifest = R24 / "stage-b-manifest.json"
    out[str(manifest.relative_to(ROOT).as_posix())] = sha256_file(manifest)
    dest = R24 / "stage-b-sha256-manifest.json"
    dest.write_text(json.dumps(dict(sorted(out.items())), indent=2) + "\n", encoding="utf-8")
    print(dest, "entries", len(out))


if __name__ == "__main__":
    main()
