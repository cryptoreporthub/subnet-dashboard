#!/usr/bin/env python3
"""Write exam-artifacts/r24/run-plan-b.json (3 blocks, manifest slug order)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

BLOCK_PIN_ORDER: dict[int, list[str]] = {
    1: ["PRE", "POST"],
    2: ["POST", "PRE"],
    3: ["PRE", "POST"],
}


def main() -> None:
    manifest = json.loads((ROOT / "exam-artifacts/r24/stage-b-manifest.json").read_text())
    slugs = [row["slug"] for row in manifest["stageB"]]
    if len(slugs) != 12:
        raise SystemExit(f"expected 12 stage B slugs, got {len(slugs)}")

    blocks = []
    invocation_index = 0
    for block_idx in range(1, 4):
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
                    "caseIds": [f"review-gate-r24b/{slug}/1" for slug in fixture_order],
                    "evalFilter": [f"review-gate-r24b/{slug}" for slug in fixture_order],
                    "outputJson": f"exam-artifacts/r24/runs-b/inv-{nn}-{pin}-block{block_idx}.json",
                    "syspromptSha256File": f"exam-artifacts/r24/runs-b/inv-{nn}-sysprompt.sha256",
                }
            )
        blocks.append({"block": block_idx, "invocations": invocations})

    plan = {
        "stage": "B",
        "harnessParent": "b9ccd6a73295567775ab83761d1db5c2497ac0bc",
        "prePin": "23bd34f03fb4431ad29726f500f00efc9d1dd82b",
        "postPin": "a5819378e012cfe21b021bf2b6c5a52d5c4e2d7e",
        "slugs": slugs,
        "blocks": blocks,
    }
    out = ROOT / "exam-artifacts/r24/run-plan-b.json"
    out.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
