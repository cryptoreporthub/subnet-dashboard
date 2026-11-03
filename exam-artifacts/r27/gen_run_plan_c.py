#!/usr/bin/env python3
"""Write exam-artifacts/r27/run-plan-c.json (LOCK-3 block order, R23/C25 arms)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BLOCK_ARM_ORDER: dict[int, list[tuple[str, str]]] = {
    1: [("R23", "a5819378e012cfe21b021bf2b6c5a52d5c4e2d7e"), ("C25", "06269de964afc69bc81dd71156caa5bb2594bea1")],
    2: [("C25", "06269de964afc69bc81dd71156caa5bb2594bea1"), ("R23", "a5819378e012cfe21b021bf2b6c5a52d5c4e2d7e")],
    3: [("R23", "a5819378e012cfe21b021bf2b6c5a52d5c4e2d7e"), ("C25", "06269de964afc69bc81dd71156caa5bb2594bea1")],
    4: [("C25", "06269de964afc69bc81dd71156caa5bb2594bea1"), ("R23", "a5819378e012cfe21b021bf2b6c5a52d5c4e2d7e")],
    5: [("R23", "a5819378e012cfe21b021bf2b6c5a52d5c4e2d7e"), ("C25", "06269de964afc69bc81dd71156caa5bb2594bea1")],
}


def main() -> None:
    manifest = json.loads((ROOT / "exam-artifacts/r27/stage-c-manifest.json").read_text())
    slugs = [row["slug"] for row in manifest["fixtures"]]
    if len(slugs) != 24:
        raise SystemExit(f"expected 24 slugs, got {len(slugs)}")

    blocks = []
    invocation_index = 0
    for block_idx in range(1, 6):
        invocations = []
        for arm, pin_sha in BLOCK_ARM_ORDER[block_idx]:
            invocation_index += 1
            nn = f"{invocation_index:02d}"
            invocations.append(
                {
                    "invocationIndex": invocation_index,
                    "arm": arm,
                    "pinSha": pin_sha,
                    "block": block_idx,
                    "fixtureOrder": slugs[:],
                    "caseIds": [f"review-gate-r27/{slug}/1" for slug in slugs],
                    "evalFilter": [f"review-gate-r27/{slug}" for slug in slugs],
                    "outputJson": f"exam-artifacts/r27/runs-c/inv-{nn}-{arm}-block{block_idx}.json",
                    "syspromptSha256File": f"exam-artifacts/r27/runs-c/inv-{nn}-sysprompt.sha256",
                }
            )
        blocks.append({"block": block_idx, "invocations": invocations})

    plan = {
        "stage": "C",
        "round": "r27",
        "harnessParent": "b9ccd6a73295567775ab83761d1db5c2497ac0bc",
        "r23Pin": "a5819378e012cfe21b021bf2b6c5a52d5c4e2d7e",
        "c25Pin": "06269de964afc69bc81dd71156caa5bb2594bea1",
        "slugs": slugs,
        "blocks": blocks,
        "slotNote": "240 scored slots per arm (24 fixtures × 10 invocations); PASS subset 120 slots (12×10)",
    }
    out = ROOT / "exam-artifacts/r27/run-plan-c.json"
    out.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
