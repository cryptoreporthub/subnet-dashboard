"""A fresh process's first ledger_db read must not wait on the soul_map writer lock.

The legacy weight drop is already done: soul_map.json carries the migrated marker and
ledger.db holds its soul_map import row, so the read has nothing to import or write. A
writer holding the soul_map lock for a while must not stall that first read.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from internal.store import ledger_db

REPO_ROOT = Path(__file__).resolve().parents[1]
HOLD_SECONDS = 2.0
READ_BOUND_SECONDS = 0.5
# The reader must start with at least this much of the hold left, or the test measures nothing.
MIN_HOLD_LEFT_AT_READ_START = 1.0

_HOLDER = r"""
import json, os, sys, time
sys.path.insert(0, sys.argv[1])
from internal.store.soul_map_io import write_soul_map
path, ready, hold = sys.argv[2], sys.argv[3], float(sys.argv[4])

def hold_writer_lock(blob):
    tmp = ready + ".tmp"
    with open(tmp, "w") as handle:
        json.dump({"acquired_at": time.time()}, handle)
    os.replace(tmp, ready)
    time.sleep(hold)

result = write_soul_map(hold_writer_lock, path=path)
print(result.outcome.value)
"""

_READER = r"""
import json, sys, time
sys.path.insert(0, sys.argv[1])
from internal.store import ledger_db
import internal.store.soul_map_io  # imported before the timer so only the read is measured
path = sys.argv[2]
started_at = time.time()
t0 = time.monotonic()
with ledger_db.reader(path) as conn:
    expert = ledger_db.read_kind(conn, "expert")
elapsed = time.monotonic() - t0
print(json.dumps({"started_at": started_at, "elapsed": elapsed, "expert": expert}))
"""


def _wait_for_holder(ready: Path, holder: subprocess.Popen) -> float:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if ready.exists():
            return json.loads(ready.read_text(encoding="utf-8"))["acquired_at"]
        if holder.poll() is not None:
            _, err = holder.communicate()
            raise AssertionError(f"holder exited before taking the lock: {err}")
        time.sleep(0.01)
    raise AssertionError("holder never reported it took the soul_map writer lock")


def test_first_ledger_read_is_not_blocked_by_a_soul_map_writer(tmp_path):
    soul = tmp_path / "soul_map.json"
    soul.write_text(
        json.dumps(
            {
                "adversarial_state": {
                    "council_weights": {"quant": 1.4, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0},
                    "signal_weights": {"hour": {"rsi_crossover": 1.3}},
                    "impact_strength": 0.7,
                },
                "judge_weights": {"oracle": 0.5, "echo": 0.2, "pulse": 0.3},
                "keep": {"me": [1, 2, 3]},
            }
        ),
        encoding="utf-8",
    )
    # The legacy drop happens for real here, through the production reader.
    with ledger_db.reader(str(soul)) as conn:
        assert ledger_db.read_kind(conn, "expert")["quant"] == 1.4
        state = json.loads(ledger_db.get_meta(conn, ledger_db.SOUL_MAP_MARKER))["state"]
    assert state == "loaded"
    assert ledger_db.MIGRATED_KEY in json.loads(soul.read_text(encoding="utf-8"))

    ready = tmp_path / "holder.ready"
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(REPO_ROOT), str(soul), str(ready), str(HOLD_SECONDS)],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        acquired_at = _wait_for_holder(ready, holder)
        reader = subprocess.run(
            [sys.executable, "-c", _READER, str(REPO_ROOT), str(soul)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            env=dict(os.environ),
        )
    finally:
        holder_out, holder_err = holder.communicate(timeout=30)

    assert reader.returncode == 0, f"fresh reader failed:\n{reader.stderr}"
    reading = json.loads(reader.stdout.strip().splitlines()[-1])

    hold_left = acquired_at + HOLD_SECONDS - reading["started_at"]
    assert hold_left >= MIN_HOLD_LEFT_AT_READ_START, (
        f"setup error: reader started with only {hold_left:.2f}s of hold left; measurement is invalid"
    )
    assert reading["expert"]["quant"] == 1.4

    elapsed = reading["elapsed"]
    assert elapsed < READ_BOUND_SECONDS


def test_corrupt_soul_map_after_migration_is_quarantined_and_ledger_still_serves(tmp_path):
    soul = tmp_path / "soul_map.json"
    soul.write_text(
        json.dumps({"adversarial_state": {"council_weights": {"quant": 1.4}}, "keep": {"me": [1]}}),
        encoding="utf-8",
    )
    with ledger_db.reader(str(soul)) as conn:
        assert ledger_db.read_kind(conn, "expert")["quant"] == 1.4
    assert ledger_db.MIGRATED_KEY in json.loads(soul.read_text(encoding="utf-8"))

    corrupt = b"{not json"
    soul.write_bytes(corrupt)
    before = {p.name for p in tmp_path.iterdir()}

    reader = subprocess.run(
        [sys.executable, "-c", _READER, str(REPO_ROOT), str(soul)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        env=dict(os.environ),
    )

    assert reader.returncode == 0, f"fresh reader failed:\n{reader.stderr}"
    expert = json.loads(reader.stdout.strip().splitlines()[-1])["expert"]
    assert expert["quant"] == 1.4
    quarantined = sorted(
        p for p in tmp_path.iterdir() if p.name not in before and p.name.startswith("soul_map.json.corrupt-")
    )
    assert quarantined, f"corrupt soul_map was not quarantined; new files: {sorted({p.name for p in tmp_path.iterdir()} - before)}"
    assert quarantined[0].read_bytes() == corrupt
