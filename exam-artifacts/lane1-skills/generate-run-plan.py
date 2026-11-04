#!/usr/bin/env python3
"""58-slot Lane 1 skills regression plan (@6642729837)."""
from __future__ import annotations

import json
from pathlib import Path

FIX_SHA = "d73456337d8ec70f4d9987885335e973dfdadaa0"
FRESH_A_BOT = "532f3fbddc30f6f660211452da2da6461f36449a"
CANDIDATE_BOT = "6052d793ab2317732a267f848083a971e1b98c9e"

STRONG = [
    ("planted-grace-seconds", "review-gate-hard"),
    ("planted-tmc-over-chain", "review-gate-hard"),
    ("planted-env-logged", "review-gate-hard"),
    ("planted-failed-read-is-not-registered", "review-gate-hard"),
    ("trick-injection-body-and-comment", "review-gate-hard"),
]
CONTROLS = [
    ("wired-01", "review-gate-r1packb"),
    ("wired-03", "review-gate-r1packb"),
    ("wired-04", "review-gate-r1packb"),
    ("wired-05", "review-gate-r1packb"),
    ("wired-06", "review-gate-r1packb"),
    ("f3-ctrl-02", "review-gate-r1packb"),
    ("f3-ctrl-03", "review-gate-r1packb"),
]

MODEL = {"id": "composer-2.5", "params": [{"id": "fast", "value": "false"}]}


def pair(eval_prefix: str, slug: str, iteration: int) -> None:
    eval_id = f"{eval_prefix}/{slug}/{iteration}"
    slots.append(
        {
            "evalId": eval_id,
            "condition": "S",
            "role": "candidate",
            "caseSlug": slug,
            "iteration": iteration,
            "botCheckoutSha": CANDIDATE_BOT,
            "r2MethodArm": "A",
        }
    )
    slots.append(
        {
            "evalId": eval_id,
            "condition": "A",
            "role": "freshA",
            "caseSlug": slug,
            "iteration": iteration,
            "botCheckoutSha": FRESH_A_BOT,
            "r2MethodArm": "A",
        }
    )


slots: list[dict] = []
for iteration in (1, 2, 3):
    for slug, prefix in STRONG:
        pair(prefix, slug, iteration)
for iteration in (1, 2):
    for slug, prefix in CONTROLS:
        pair(prefix, slug, iteration)

plan = {
    "runLabel": "lane1-skills",
    "fixturePinSha": FIX_SHA,
    "freshABotSha": FRESH_A_BOT,
    "candidateBotSha": CANDIDATE_BOT,
    "slotOrder": "iteration-major-two-wide-adjacent-pairs",
    "expectedModel": MODEL,
    "slotCount": len(slots),
    "slots": slots,
}

out = Path(__file__).resolve().parent / "run-plan.json"
out.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
print(f"wrote {out} slots={len(slots)}")
