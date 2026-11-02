#!/usr/bin/env python3
"""Write exam-artifacts/r24/run-plan.json (seed 20261102, 5 blocks, 10 invocations)."""
from __future__ import annotations

import json
import random
import subprocess
from pathlib import Path

SEED = 20261102
ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    manifest = json.loads((ROOT / "exam-artifacts/r24/stage-a-manifest.json").read_text())
    slugs = [row["slug"] for row in manifest["stageA"]]
    if len(slugs) != 12:
        raise SystemExit(f"expected 12 stage A slugs, got {len(slugs)}")

    rng = random.Random(SEED)
    tip = manifest.get("harnessTip") or subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    blocks = []
    for block_idx in range(1, 6):
        order = ["PRE", "POST"]
        rng.shuffle(order)
        invocations = []
        for pin in order:
            fixture_order = slugs[:]
            rng.shuffle(fixture_order)
            invocations.append(
                {
                    "pin": pin,
                    "fixtureOrder": fixture_order,
                    "caseIds": [f"review-gate-r24/{slug}/1" for slug in fixture_order],
                    "evalFilter": [f"review-gate-r24/{slug}" for slug in fixture_order],
                }
            )
        blocks.append({"block": block_idx, "invocations": invocations})

    plan = {
        "seed": SEED,
        "contentTip": tip,
        "prePin": manifest["prePin"],
        "postPin": manifest["postPin"],
        "harnessParent": manifest["harnessParent"],
        "slugs": slugs,
        "blocks": blocks,
    }
    out = ROOT / "exam-artifacts/r24/run-plan.json"
    out.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
