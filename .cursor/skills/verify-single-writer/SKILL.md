---
name: verify-single-writer
description: >-
  Prove single-writer step 1 (internal/owner_guard.py + worker startup gate) in an
  isolated temp DATA_DIR. Use before merging owner-lock changes, after rebasing
  single-writer PRs, or when debugging exit-code-3 worker blocks.
phases: LAUNCH, DOCTOR, DRIVE, EVIDENCE, CLEANUP
---

# Verify single-writer (owner_guard)

**Scope:** `internal/owner_guard.py`, `internal/worker.py` startup gate, volume marker + flock lock.  
**Out of scope:** web lifespan paths, Fly volume mount proof on real hardware, Step 2 writer wiring.

**Prerequisites:** Single-writer step 1 merged (or PR head checked out): `internal/owner_guard.py` and `tests/test_owner_guard.py` must exist. See [AGENTS.md](../../../AGENTS.md) (venv, pytest) and [DEPLOY.md](../../../DEPLOY.md) (`DATA_VOLUME_ID`, volume marker runbook when present).

**One-liner helper:** from repo root, `bash scripts/verify-owner-guard.sh` (runs DOCTOR → DRIVE → EVIDENCE → CLEANUP; idempotent; temp `DATA_DIR` only).

## LAUNCH

1. Repo root: `cd "$(git rev-parse --show-toplevel)"`.
2. Python: `source .venv/bin/activate` (or `.venv/bin/python` / `.venv/bin/pytest` directly — same as AGENTS.md).
3. Do **not** use repo `data/` for drives. Export a fresh dir per run:
   ```bash
   export DATA_DIR="$(mktemp -d)"
   export VERIFY_EVIDENCE_DIR="${VERIFY_EVIDENCE_DIR:-/opt/cursor/artifacts/verify-single-writer-$(date -u +%Y%m%dT%H%M%SZ)}"
   mkdir -p "$VERIFY_EVIDENCE_DIR"
   export PYTHONPATH="$(pwd)"
   ```
4. Clear Fly/prod stubs unless a drive step sets them: `unset FLY_APP_NAME FLY_MACHINE_ID DATA_VOLUME_ID DATA_DIR_IS_VOLUME OWNER_GUARD_SKIP`.
5. Default is **dev** (non-prod-like): owner lock may bootstrap a v2 marker under `$DATA_DIR`. Do not set `OWNER_GUARD_SKIP` unless you are explicitly testing skip behavior in pytest.

## DOCTOR

Read-only; stop if any step fails.

1. `[ -x .venv/bin/python ]` — venv present (Cloud Agent startup script creates `.venv`).
2. `.venv/bin/python -c "import internal.owner_guard as og; print(og.WRITE_OWNER_LOCK_NAME)"` — module importable.
3. `.venv/bin/pytest --collect-only -q tests/test_owner_guard.py` — test module matches current APIs (see fixtures `_subprocess_env`, `owner_env`, `prod_mount` in that file).

## DRIVE

Exercise real refusal and happy paths (mirrors `tests/test_owner_guard.py`; no pytest required for this skill).

### DRIVE 1 — Worker refusal (exit 3)

Prod-like temp volume with data but **no** `DATA_VOLUME_ID` pin → worker must refuse before background writers start.

Pattern: `test_worker_blocked_subprocess_e2e` / `test_worker_blocked_exits_3_and_never_logs_running`.

```bash
export ROOT="$(pwd)"
DATA="$DATA_DIR"
mkdir -p "$DATA"
echo '{}' > "$DATA/soul_map.json"

export MOUNT_LINE="999 998 0:42 / $(realpath "$DATA") rw,relatime - ext4 /dev/vdc rw"
export DATA_DIR="$DATA" FLY_APP_NAME=subnet-dashboard
unset DATA_VOLUME_ID PYTEST_CURRENT_TEST

.venv/bin/python - <<'PY'
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
print("exit", proc.returncode)
print((proc.stdout or "") + (proc.stderr or ""))
sys.exit(0 if proc.returncode == 3 else 1)
PY
```

**Pass:** exit code **3**; combined stdout/stderr contains `volume_pin_missing` or `BLOCKED` (see `internal.owner_guard.VOLUME_PIN_MISSING_HINT`).

### DRIVE 2 — Happy path lock acquire (dev)

Isolated dir, no prod env → `try_acquire_write_owner_lock()` succeeds; reads `inspect_owner_guard().writes_allowed`.

Pattern: `test_dev_creates_volume_marker_when_not_prod_like`, `owner_env` fixture.

```bash
unset FLY_APP_NAME FLY_MACHINE_ID DATA_VOLUME_ID OWNER_GUARD_SKIP
export DATA_DIR="$DATA_DIR"

.venv/bin/python - <<'PY'
import json, os, sys
import internal.file_utils as fu
import internal.owner_guard as og

data = os.environ["DATA_DIR"]
fu.DATA_DIR = data
og.reset_owner_guard_for_tests()
ok, detail = og.try_acquire_write_owner_lock()
state = og.inspect_owner_guard()
print(json.dumps({"ok": ok, "detail": detail, "writes_allowed": state.writes_allowed}, indent=2))
sys.exit(0 if ok and state.writes_allowed else 1)
PY
```

**Pass:** `ok` true, `writes_allowed` true, v2 marker file under `$DATA_DIR/.data_volume_marker.json`.

## EVIDENCE

Write under `$VERIFY_EVIDENCE_DIR` (survives CLEANUP of `$DATA_DIR`):

- `drive1-exit-code.txt` — worker refusal exit code (expect `3`).
- `drive1-log-tail.txt` — last 40 lines of DRIVE 1 combined output.
- `drive2-inspect.json` — JSON from happy-path `inspect_owner_guard()` + acquire detail.
- `doctor-collect.txt` — optional: `pytest --collect-only` summary if captured by helper script.

## CLEANUP

1. Kill any background lock-holder PID you started (helper script tracks `$LOCK_HOLDER_PID`).
2. `rm -rf "$DATA_DIR"` — only the temp dir from LAUNCH; never delete repo `data/`.
3. Leave `$VERIFY_EVIDENCE_DIR` intact for the agent run / PR proof.

## Helpers

| Script | Purpose |
|--------|---------|
| `scripts/verify-owner-guard.sh` | Runs DOCTOR, DRIVE 1+2, EVIDENCE, CLEANUP; exit 0 on full pass, 2 on DOCTOR fail, 1 on DRIVE fail |

## References

- Subprocess env helper: `_subprocess_env()` in `tests/test_owner_guard.py` (sets `PYTHONPATH` to repo root, strips `PYTEST_CURRENT_TEST`).
- Prod-like mount stub: `_fake_mountinfo_for(data_dir)` in the same test module.
- Worker must not log `background worker running` when blocked (`test_worker_blocked_exits_3_and_never_logs_running`).
