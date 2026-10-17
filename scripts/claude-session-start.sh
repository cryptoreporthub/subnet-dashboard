#!/usr/bin/env bash
# Claude Code cloud SessionStart bootstrap: venv + pytest + pstack. Never fails the session.
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
if [ ! -x .venv/bin/pytest ]; then
  python3 -m venv .venv && .venv/bin/pip -q install -r requirements.txt pytest httpx || echo "venv bootstrap failed" >&2
fi
bash scripts/install-pstack.sh || echo "pstack install failed (non-fatal)" >&2
exit 0
