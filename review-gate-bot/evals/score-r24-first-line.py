#!/usr/bin/env python3
"""r24 Stage A scorer: posted first-line verdict only (no dets).

LOCK-3: identical successful post_verdict calls → that verdict; conflicting posts,
no post, or unparseable body → NO_POST (invalid).
"""
import json
import re
import sys
from pathlib import Path

CATEGORIES = ("PASS", "MODIFY", "FAIL", "NO_POST")


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
        out.append(inp)
    return out


def verdict_from_post(post: dict, final_text: str = "") -> str | None:
    v = post.get("verdict")
    if isinstance(v, str) and v.upper() in ("PASS", "MODIFY", "FAIL", "BLOCK"):
        return "FAIL" if v.upper() in ("FAIL", "BLOCK") else v.upper()
    body = post.get("body") or final_text or ""
    tok = first_line_token(body)
    return tok if tok in ("PASS", "MODIFY", "FAIL") else None


def classify_run(r: dict) -> str:
    posts = post_verdict_calls(r)
    if not posts:
        return "NO_POST"
    verdicts: list[str] = []
    for post in posts:
        v = verdict_from_post(post, r.get("finalText") or "")
        if v is None:
            return "NO_POST"
        verdicts.append(v)
    if len(set(verdicts)) == 1:
        return verdicts[0]
    return "NO_POST"


def duplicate_post_count(r: dict) -> int:
    """Descriptive only (LOCK-3); not used for category."""
    posts = post_verdict_calls(r)
    return max(0, len(posts) - 1)


def score_file(path: Path, expected: str | None = None) -> dict:
    doc = json.loads(path.read_text())
    rows = []
    for r in doc.get("results") or []:
        cat = classify_run(r)
        row = {"id": r.get("id"), "category": cat, "duplicatePosts": duplicate_post_count(r)}
        if expected:
            row["expected"] = expected
            row["match"] = cat == expected or (expected == "FAIL" and cat == "FAIL")
        rows.append(row)
    return {"path": str(path), "runs": rows}


def main() -> None:
    for arg in sys.argv[1:]:
        p = Path(arg)
        if p.suffix == ".json" and p.exists():
            print(json.dumps(score_file(p), sort_keys=True))
        else:
            print(json.dumps({"error": f"not a file: {arg}"}))


if __name__ == "__main__":
    main()
