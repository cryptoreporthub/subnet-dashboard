#!/usr/bin/env python3
"""py_compile + workflow YAML parse + pyflakes on Stage A/B fixture head Python."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def stage_a_fixtures() -> list[tuple[str, Path]]:
    manifest = json.loads((ROOT / "exam-artifacts/r24/stage-a-manifest.json").read_text())
    out = []
    for row in manifest["stageA"]:
        name = row["fixture"]
        repo = ROOT / "review-gate-bot/evals/fixtures" / name / "repo.json"
        out.append((f"stage-a:{name}", repo))
    return out


def stage_b_fixtures() -> list[tuple[str, Path]]:
    manifest = json.loads((ROOT / "exam-artifacts/r24/stage-b-manifest.json").read_text())
    out = []
    for row in manifest["stageB"]:
        name = row["fixture"]
        repo = ROOT / "exam-artifacts/r24/fixtures/stage-b" / name / "repo.json"
        out.append((f"stage-b:{row['slug']}", repo))
    return out


def head_files(repo_path: Path) -> dict[str, str]:
    doc = json.loads(repo_path.read_text())
    return doc.get("files") or {}


def run_gate(label: str, files: dict[str, str]) -> list[str]:
    lines: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        for rel, content in sorted(files.items()):
            path = tdp / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            if rel.endswith(".py"):
                proc = subprocess.run(
                    [sys.executable, "-m", "py_compile", str(path)],
                    capture_output=True,
                    text=True,
                )
                lines.append(f"[{label}] py_compile {rel} exit={proc.returncode}")
                if proc.stderr.strip():
                    lines.append(proc.stderr.strip())
                pf = subprocess.run(
                    [sys.executable, "-m", "pyflakes", str(path)],
                    capture_output=True,
                    text=True,
                )
                lines.append(f"[{label}] pyflakes {rel} exit={pf.returncode}")
                out = (pf.stdout or "") + (pf.stderr or "")
                undefined = [ln for ln in out.splitlines() if "undefined name" in ln or "undefined local" in ln]
                if undefined:
                    lines.extend(undefined)
                    lines.append(f"[{label}] pyflakes {rel} UNDEFINED=1")
                elif out.strip():
                    lines.extend(out.strip().splitlines())
            if rel.endswith((".yml", ".yaml")) and ".github/workflows" in rel:
                try:
                    import yaml  # type: ignore

                    yaml.safe_load(content)
                    lines.append(f"[{label}] yaml_parse {rel} ok")
                except Exception as e:
                    lines.append(f"[{label}] yaml_parse {rel} FAIL: {e}")
    return lines


def main() -> int:
    all_lines: list[str] = []
    # Stage B uses manifest — run after manifest exists; caller regenerates first.
    for label, repo in stage_a_fixtures() + stage_b_fixtures():
        if not repo.is_file():
            all_lines.append(f"MISSING {label} {repo}")
            continue
        files = head_files(repo)
        all_lines.extend(run_gate(label, files))
    text = "\n".join(all_lines) + "\n"
    sys.stdout.write(text)
    out = ROOT / "exam-artifacts/r24/fixture-gate-output.txt"
    out.write_text(text, encoding="utf-8")
    failed = any("UNDEFINED=1" in ln or " FAIL:" in ln or "py_compile" in ln and "exit=1" in ln for ln in all_lines)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
