#!/usr/bin/env python3
"""Scorer v2 (R0.3): per-case expected verdict table; catch/over-block by family, stack, arm.

Retires the pooled semantic catch /63 total. Input: eval results JSON (+ optional manifest).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PATH = ROOT / "evals/score-v2-expected.json"

VERDICTS = ("PASS", "MODIFY", "FAIL", "NO_POST")


def load_expected() -> dict[str, dict]:
    doc = json.loads(EXPECTED_PATH.read_text())
    cases = dict(doc["cases"])
    manifest_path = ROOT.parent / "exam-artifacts/r27/stage-c-manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text())
        for row in manifest.get("fixtures") or []:
            slug = row.get("slug")
            fixture = row.get("fixture") or slug
            oracle = row.get("oracle") or "MODIFY"
            key = f"review-gate-r27/{slug}"
            cases.setdefault(
                key,
                {
                    "expected": oracle,
                    "family": fixture.split("-")[0] if fixture else slug,
                    "semantic": True,
                },
            )
    return cases


def first_line_token(text: str) -> str | None:
    if not text:
        return None
    line = text.strip().splitlines()[0].strip()
    m = re.match(r"^(PASS|MODIFY|FAIL|BLOCK)\b", line, re.I)
    if not m:
        return None
    v = m.group(1).upper()
    return "FAIL" if v == "BLOCK" else v


def post_verdict_calls(r: dict) -> list[dict]:
    out = []
    for tc in r.get("toolCalls") or []:
        if tc.get("toolName") != "post_verdict":
            continue
        if tc.get("isError") or tc.get("status") == "failed":
            continue
        inp = tc.get("input") or tc.get("args") or {}
        out.append({"input": inp, "output": tc.get("output") or ""})
    return out


def post_was_accepted(output: str) -> bool:
    if not output:
        return False
    try:
        doc = json.loads(output)
    except json.JSONDecodeError:
        return False
    return doc.get("posted") is True


def classify_run(r: dict) -> str:
    accepted: list[str] = []
    for call in post_verdict_calls(r):
        if not post_was_accepted(call["output"]):
            continue
        v = verdict_from_post(call["input"], r.get("finalText") or "")
        if v is None:
            return "NO_POST"
        accepted.append(v)
    if not accepted:
        return "NO_POST"
    if len(set(accepted)) == 1:
        return accepted[0]
def verdict_from_post(post: dict, final_text: str = "") -> str | None:
    v = post.get("verdict")
    if isinstance(v, str) and v.upper() in ("PASS", "MODIFY", "FAIL", "BLOCK"):
        return "FAIL" if v.upper() in ("FAIL", "BLOCK") else v.upper()
    body = post.get("body") or final_text or ""
    tok = first_line_token(body)
    return tok if tok in ("PASS", "MODIFY", "FAIL") else None


def parse_arm_stack(run_id: str, meta: dict | None) -> tuple[str, str]:
    arm = (meta or {}).get("arm") or "unknown"
    stack = (meta or {}).get("stack") or "unknown"
    m = re.search(r"/(PRE|POST|R23|C25|block\d+)", run_id or "")
    if m and arm == "unknown":
        arm = m.group(1)
    return stack, arm


def fixture_from_id(case_id: str) -> str:
    # review-gate-hard/planted-blank-reload/1 -> planted-blank-reload
    parts = (case_id or "").split("/")
    if len(parts) >= 2:
        return parts[1]
    return case_id or "unknown"


def score_results(doc: dict, expected: dict[str, dict]) -> dict:
    rows = []
    by_family: dict[str, dict] = {}
    by_stack: dict[str, dict] = {}
    by_arm: dict[str, dict] = {}

    def bump(bucket: dict, key: str, field: str) -> None:
        b = bucket.setdefault(key, {"catch": 0, "miss": 0, "over_block": 0, "clean_pass": 0, "n": 0})
        b[field] = b.get(field, 0) + 1
        b["n"] = b.get("n", 0) + 1

    for r in doc.get("results") or []:
        case_id = r.get("id") or ""
        fixture = fixture_from_id(case_id)
        exp_row = expected.get(case_id) or expected.get(fixture) or expected.get(f"review-gate-hard/{fixture}")
        expected_verdict = (exp_row or {}).get("expected")
        family = (exp_row or {}).get("family") or fixture.split("-")[0]
        semantic = (exp_row or {}).get("semantic", True)
        state_family = family == "state" or (isinstance(family, str) and family.startswith("state-"))
        if state_family:
            semantic = False
        stack, arm = parse_arm_stack(case_id, r.get("meta") if isinstance(r.get("meta"), dict) else None)
        actual = classify_run(r)
        row = {
            "id": case_id,
            "fixture": fixture,
            "family": family,
            "stack": stack,
            "arm": arm,
            "actual": actual,
            "expected": expected_verdict,
        }
        if expected_verdict:
            row["match"] = actual == expected_verdict or (
                expected_verdict == "FAIL" and actual == "FAIL"
            )
            if semantic:
                if expected_verdict in ("MODIFY", "FAIL") and actual in ("MODIFY", "FAIL"):
                    bump(by_family, family, "catch")
                    bump(by_stack, stack, "catch")
                    bump(by_arm, arm, "catch")
                elif expected_verdict in ("MODIFY", "FAIL") and actual == "PASS":
                    bump(by_family, family, "miss")
                    bump(by_stack, stack, "miss")
                    bump(by_arm, arm, "miss")
                elif expected_verdict == "PASS" and actual == "PASS":
                    bump(by_family, family, "clean_pass")
                    bump(by_stack, stack, "clean_pass")
                    bump(by_arm, arm, "clean_pass")
                elif expected_verdict == "PASS" and actual in ("MODIFY", "FAIL"):
                    bump(by_family, family, "over_block")
                    bump(by_stack, stack, "over_block")
                    bump(by_arm, arm, "over_block")
        rows.append(row)

    return {
        "rows": rows,
        "byFamily": by_family,
        "byStack": by_stack,
        "byArm": by_arm,
        "retiredMetric": "pooled_semantic_catch_over_63_total",
    }


def main() -> None:
    expected = load_expected()
    for arg in sys.argv[1:]:
        path = Path(arg)
        if not path.is_file():
            print(json.dumps({"error": f"not a file: {arg}"}))
            continue
        doc = json.loads(path.read_text())
        print(json.dumps(score_results(doc, expected), sort_keys=True))


if __name__ == "__main__":
    main()
