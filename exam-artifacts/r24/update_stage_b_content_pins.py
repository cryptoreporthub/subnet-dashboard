#!/usr/bin/env python3
"""Set stage-b-manifest.json contentPins for RUN-READY-B."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "exam-artifacts/r24/stage-b-manifest.json"

PIN_PATHS = {
    "runPlanB": ROOT / "exam-artifacts/r24/run-plan-b.json",
    "runnerB": ROOT / "review-gate-bot/evals/review-gate-r24b.eval.ts",
    "prompts": ROOT / "review-gate-bot/evals/r24-prompts.ts",
    "scorer": ROOT / "review-gate-bot/evals/score-r24-first-line.py",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def main() -> None:
    doc = json.loads(MANIFEST_PATH.read_text())
    doc.pop("contentPins", None)
    manifest_body = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    pins = {
        "stageBManifest": sha256_bytes(manifest_body.encode()),
        "runPlanB": sha256_file(PIN_PATHS["runPlanB"]),
        "runnerB": sha256_file(PIN_PATHS["runnerB"]),
        "prompts": sha256_file(PIN_PATHS["prompts"]),
        "scorer": sha256_file(PIN_PATHS["scorer"]),
    }
    doc["contentPins"] = pins
    doc["runnerB"] = "review-gate-bot/evals/review-gate-r24b.eval.ts"
    doc["runPlanB"] = "exam-artifacts/r24/run-plan-b.json"
    doc["scorer"] = "review-gate-bot/evals/score-r24-first-line.py"
    doc["prompts"] = "review-gate-bot/evals/r24-prompts.ts"
    MANIFEST_PATH.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(pins, indent=2))


if __name__ == "__main__":
    main()
