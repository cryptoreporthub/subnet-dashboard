#!/usr/bin/env python3
"""R1 pack B — redaction stratum fixture generator (stub).

PLAN-v1.3: six bug fixtures where planted logic uses credential-like names so
`redactSecrets` on read_repo_file / get_pr_diff patches can blind the reviewer.

Usage (future):
  python3 generate_redaction_stratum.py --out exam-artifacts/r1/pack-b/fixtures

Today: prints the stratum table and exits 0 (no writes until mutation rules land).
"""
from __future__ import annotations

import argparse
from pathlib import Path

STRATUM = [
    ("r1-redact-01-token-count", "token_count", "wrong guard on token_count > 0"),
    ("r1-redact-02-max-tokens", "max_tokens", "wrong cap from max_tokens constant"),
    ("r1-redact-03-api-key-env", "api_key", "empty api_key accepted"),
    ("r1-redact-04-password-field", "password", "blank password accepted"),
    ("r1-redact-05-bearer-header", "bearer", "missing bearer treated as OK"),
    ("r1-redact-06-secret-config", "client_secret", "wrong client_secret default"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "fixtures")
    args = ap.parse_args()
    print("R1 redaction stratum (6 bug fixtures); output dir:", args.out)
    for fid, name, note in STRATUM:
        print(f"  {fid}: {name} — {note}")
    print("generator stub: no repo.json written yet (blocked on RUN-READY-R1PRE)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
