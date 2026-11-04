#!/usr/bin/env bash
# Sync review-gate-bot runtime (bot/ + tests/) from a pinned commit; keep evals/fixtures at fixture pin.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SHA="${1:?bot commit sha}"
git -C "$REPO_ROOT" checkout "$SHA" -- review-gate-bot/bot review-gate-bot/tests
