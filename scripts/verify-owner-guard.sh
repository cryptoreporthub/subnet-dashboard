#!/usr/bin/env bash
# Idempotent owner_guard verification (temp DATA_DIR only). See .cursor/skills/verify-single-writer/SKILL.md
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${ROOT}/.venv/bin/python"
PT="${ROOT}/.venv/bin/pytest"

DATA_DIR="${DATA_DIR:-$(mktemp -d)}"
CREATED_DATA_DIR=0
if [[ -z "${VERIFY_KEEP_DATA_DIR:-}" ]]; then
  CREATED_DATA_DIR=1
fi

VERIFY_EVIDENCE_DIR="${VERIFY_EVIDENCE_DIR:-/opt/cursor/artifacts/verify-single-writer-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$VERIFY_EVIDENCE_DIR"

LOCK_HOLDER_PID=""

cleanup() {
  if [[ -n "$LOCK_HOLDER_PID" ]] && kill -0 "$LOCK_HOLDER_PID" 2>/dev/null; then
    kill "$LOCK_HOLDER_PID" 2>/dev/null || true
    wait "$LOCK_HOLDER_PID" 2>/dev/null || true
  fi
  if [[ "$CREATED_DATA_DIR" -eq 1 ]] && [[ -d "$DATA_DIR" ]]; then
    rm -rf "$DATA_DIR"
  fi
}
trap cleanup EXIT

doctor() {
  if [[ ! -x "$PY" ]]; then
    echo "DOCTOR FAIL: missing .venv — see AGENTS.md" >&2
    exit 2
  fi
  if ! "$PY" -c "import internal.owner_guard as og; assert og.WRITE_OWNER_LOCK_NAME" 2>/dev/null; then
    echo "DOCTOR FAIL: internal.owner_guard not importable (single-writer step 1 not present?)" >&2
    exit 2
  fi
  if [[ ! -f tests/test_owner_guard.py ]]; then
    echo "DOCTOR FAIL: tests/test_owner_guard.py missing" >&2
    exit 2
  fi
  "$PT" --collect-only -q tests/test_owner_guard.py >"$VERIFY_EVIDENCE_DIR/doctor-collect.txt" 2>&1
}

drive_refusal() {
  local data="$DATA_DIR"
  mkdir -p "$data"
  echo '{}' >"$data/soul_map.json"
  local mount_line
  mount_line="999 998 0:42 / $(realpath "$data") rw,relatime - ext4 /dev/vdc rw"

  EVIDENCE="$VERIFY_EVIDENCE_DIR" ROOT="$ROOT" DATA_DIR="$data" MOUNT_LINE="$mount_line" "$PY" - <<'PY'
import os, subprocess, sys, textwrap
root = os.environ["ROOT"]
data = os.environ["DATA_DIR"]
mount_line = os.environ["MOUNT_LINE"]
script = textwrap.dedent(f"""
import os
os.environ["DATA_DIR"] = {data!r}
os.environ["FLY_APP_NAME"] = "subnet-dashboard"
os.environ.pop("DATA_VOLUME_ID", None)
os.environ.pop("PYTEST_CURRENT_TEST", None)
import internal.data_volume as dv
dv._read_mountinfo = lambda: [{mount_line!r}]
from internal.worker import main
main()
""")
env = os.environ.copy()
env["PYTHONPATH"] = root
env.pop("PYTEST_CURRENT_TEST", None)
proc = subprocess.run(
    [sys.executable, "-c", script],
    cwd=root,
    env=env,
    capture_output=True,
    text=True,
    timeout=30,
)
combined = (proc.stdout or "") + (proc.stderr or "")
print(combined)
if proc.returncode != 3:
    sys.exit(1)
hint = "volume_pin_missing"
if hint not in combined and "BLOCKED" not in combined:
    sys.exit(1)
open(os.environ["EVIDENCE"] + "/drive1-exit-code.txt", "w").write(str(proc.returncode) + "\n")
lines = combined.splitlines()
tail = "\n".join(lines[-40:]) + ("\n" if lines else "")
open(os.environ["EVIDENCE"] + "/drive1-log-tail.txt", "w").write(tail)
PY
}

drive_happy() {
  unset FLY_APP_NAME FLY_MACHINE_ID DATA_VOLUME_ID OWNER_GUARD_SKIP || true
  export DATA_DIR
  EVIDENCE="$VERIFY_EVIDENCE_DIR" DATA_DIR="$DATA_DIR" "$PY" - <<'PY'
import json, os, sys
import internal.file_utils as fu
import internal.owner_guard as og

data = os.environ["DATA_DIR"]
fu.DATA_DIR = data
og.reset_owner_guard_for_tests()
ok, detail = og.try_acquire_write_owner_lock()
state = og.inspect_owner_guard()
payload = {"ok": ok, "detail": detail, "writes_allowed": state.writes_allowed, "reason": state.reason}
path = os.path.join(os.environ["EVIDENCE"], "drive2-inspect.json")
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2)
    handle.write("\n")
if not (ok and state.writes_allowed):
    sys.exit(1)
PY
}

main() {
  export PYTHONPATH="$ROOT"
  export VERIFY_EVIDENCE_DIR
  doctor
  EVIDENCE="$VERIFY_EVIDENCE_DIR" ROOT="$ROOT" drive_refusal
  drive_happy
  echo "verify-single-writer: OK evidence -> $VERIFY_EVIDENCE_DIR"
}

main "$@"
