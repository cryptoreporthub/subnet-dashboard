#!/usr/bin/env bash
# Claude Code cloud SessionStart bootstrap: venv + pytest + pstack. Synchronous, idempotent, never fails the session.
# .venv/.ready is written last, so a killed pip install is retried instead of trusted.
[ "${CLAUDE_CODE_REMOTE:-true}" = "true" ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
if [ ! -f .venv/.ready ]; then
  rm -rf .venv
  python3 -m venv .venv \
    && .venv/bin/pip -q install -r requirements.txt pytest httpx \
    && touch .venv/.ready \
    || echo "venv bootstrap failed" >&2
fi
bash scripts/install-pstack.sh || echo "pstack install failed (non-fatal)" >&2
exit 0
