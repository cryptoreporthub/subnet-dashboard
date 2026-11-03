#!/usr/bin/env python3
"""Write exam-artifacts/r24/run-plan-rerun.json (LOCK-3 fixed block order, registered eval order)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Counterbalanced pin order per block (no shuffle).
BLOCK_PIN_ORDER: dict[int, list[str]] = {
    1: ["PRE", "POST"],
    2: ["POST", "PRE"],
    3: ["PRE", "POST"],
    4: ["POST", "PRE"],
    5: ["PRE", "POST"],
}


def main() -> None:
    manifest = json.loads((ROOT / "exam-artifacts/r24/stage-a-manifest.json").read_text())
    slugs = [row["slug"] for row in manifest["stageA"]]
    if len(slugs) != 12:
        raise SystemExit(f"expected 12 stage A slugs, got {len(slugs)}")

    blocks = []
    invocation_index = 0
    for block_idx in range(1, 6):
        invocations = []
        for pin in BLOCK_PIN_ORDER[block_idx]:
            invocation_index += 1
            nn = f"{invocation_index:02d}"
            fixture_order = slugs[:]
            invocations.append(
                {
                    "invocationIndex": invocation_index,
                    "pin": pin,
                    "fixtureOrder": fixture_order,
                    "caseIds": [f"review-gate-r24/{slug}/1" for slug in fixture_order],
                    "evalFilter": [f"review-gate-r24/{slug}" for slug in fixture_order],
                    "outputJson": f"exam-artifacts/r24/runs-rerun/inv-{nn}-{pin}-block{block_idx}.json",
                    "syspromptSha256File": f"exam-artifacts/r24/runs-rerun/inv-{nn}-sysprompt.sha256",
                }
            )
        blocks.append({"block": block_idx, "invocations": invocations})

    plan = {
        "rerun": "lock-3",
        "harnessParent": manifest["harnessParent"],
        "prePin": manifest["prePin"],
        "postPin": manifest["postPin"],
        "slugs": slugs,
        "blocks": blocks,
    }
    out = ROOT / "exam-artifacts/r24/run-plan-rerun.json"
    out.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
