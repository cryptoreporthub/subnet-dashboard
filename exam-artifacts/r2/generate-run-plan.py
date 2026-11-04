#!/usr/bin/env python3
"""Emit R2 run-plan.json: 268 slots, iteration-major two-wide (arm then fresh A when first needed)."""
from __future__ import annotations

import json
from pathlib import Path

FIX_SHA = "d73456337d8ec70f4d9987885335e973dfdadaa0"
BASE_BOT = "532f3fbddc30f6f660211452da2da6461f36449a"
ARM_E_BOT = "acad7f3dc9e09f92703aa049f37601a7fc7acf1e"
ARM_R_BOT = "281b13042ef5405448ec5934151dba7a401148d4"

F1 = [f"f1-{n:02d}" for n in range(1, 7)]
F2 = [f"f2-{n:02d}" for n in range(1, 7)]
GEN = [f"gen-{n:02d}" for n in range(1, 7)]
F4 = [f"f4-{n:02d}" for n in range(1, 7)]
REDACT = [f"redact-{n:02d}" for n in range(1, 7)]
CONTROLS = ["wired-01", "wired-03", "wired-04", "wired-05", "wired-06", "f3-ctrl-02", "f3-ctrl-03"]
CONDITIONS = ["A", "B", "E", "R", "F"]

MODEL = {"id": "composer-2.5", "params": [{"id": "fast", "value": "false"}]}


def bot_for_condition(cond: str) -> str:
    if cond == "E":
        return ARM_E_BOT
    if cond == "R":
        return ARM_R_BOT
    return BASE_BOT


def method_arm_for_condition(cond: str) -> str:
    return cond if cond in ("A", "B", "F", "R") else "A"


def slot(cond: str, slug: str, iteration: int, role: str) -> dict:
    return {
        "evalId": f"review-gate-r1packb/{slug}/{iteration}",
        "condition": cond,
        "role": role,
        "caseSlug": slug,
        "iteration": iteration,
        "botCheckoutSha": bot_for_condition(cond),
        "r2MethodArm": method_arm_for_condition(cond),
    }


def main() -> None:
    slots: list[dict] = []
    for iteration in (1, 2, 3):
        a_done: set[str] = set()

        def maybe_a(slug: str) -> None:
            if slug in a_done:
                return
            slots.append(slot("A", slug, iteration, "freshA"))
            a_done.add(slug)

        for slug in F1:
            slots.append(slot("E", slug, iteration, "armTarget"))
            maybe_a(slug)
            slots.append(slot("B", slug, iteration, "armTarget"))
            maybe_a(slug)
        for slug in F2 + GEN:
            slots.append(slot("B", slug, iteration, "armTarget"))
            maybe_a(slug)
        for slug in F4:
            slots.append(slot("R", slug, iteration, "armTarget"))
            maybe_a(slug)
        for slug in REDACT:
            slots.append(slot("F", slug, iteration, "armTarget"))
            maybe_a(slug)

        pool30 = F1 + F2 + GEN + F4 + REDACT
        for slug in pool30:
            maybe_a(slug)

    for iteration in (1, 2):
        for cond in CONDITIONS:
            for slug in CONTROLS:
                slots.append(slot(cond, slug, iteration, "control"))

    assert len(slots) == 268, len(slots)
    plan = {
        "runLabel": "R2",
        "fixturePinSha": FIX_SHA,
        "baseBotSha": BASE_BOT,
        "armEBotSha": ARM_E_BOT,
        "armRBotSha": ARM_R_BOT,
        "slotOrder": "iteration-major-two-wide",
        "iterationsTarget": 3,
        "iterationsControl": 2,
        "expectedModel": MODEL,
        "slotCount": len(slots),
        "slots": slots,
    }
    out = Path(__file__).with_name("run-plan.json")
    out.write_text(json.dumps(plan, indent=2) + "\n")
    print(f"wrote {out} slots={len(slots)}")


if __name__ == "__main__":
    main()
