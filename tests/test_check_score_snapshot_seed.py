import os
import shutil
import subprocess
import sys
import uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE = os.path.join(ROOT, "scripts", "check_score_snapshot_seed.py")
REAL_SEED = os.path.join(ROOT, "data_seeds", "score_snapshots.json")


def _run(cwd, seed_env=None):
    env = {k: v for k, v in os.environ.items() if k != "SCORE_SNAPSHOT_SEED_PATH"}
    if seed_env is not None:
        env["SCORE_SNAPSHOT_SEED_PATH"] = seed_env
    return subprocess.run([sys.executable, GATE], cwd=cwd, env=env, capture_output=True, text=True)


@pytest.mark.parametrize("cwd", [ROOT, "/tmp"])
def test_the_gate_passes_the_committed_seed_from_any_cwd(cwd):
    proc = _run(cwd)
    assert proc.returncode == 0, proc.stderr
    assert "seed ok" in proc.stdout


def test_a_valid_seed_in_a_sibling_directory_sharing_the_prefix_is_rejected():
    sibling = os.path.join(ROOT, f"data_seeds_backup_{uuid.uuid4().hex}")
    os.makedirs(sibling)
    try:
        shutil.copy(REAL_SEED, os.path.join(sibling, "score_snapshots.json"))
        rel = os.path.join(os.path.basename(sibling), "score_snapshots.json")
        for seed_env in (rel, os.path.join(sibling, "score_snapshots.json")):
            proc = _run(ROOT, seed_env)
            assert proc.returncode == 2, (seed_env, proc.stdout, proc.stderr)
            assert "data_seeds" in proc.stderr
    finally:
        shutil.rmtree(sibling)


def test_a_valid_seed_under_data_seeds_is_accepted():
    copy = os.path.join(ROOT, "data_seeds", f"copy_{uuid.uuid4().hex}.json")
    shutil.copy(REAL_SEED, copy)
    try:
        for seed_env in (os.path.relpath(copy, ROOT), copy):
            proc = _run(ROOT, seed_env)
            assert proc.returncode == 0, (seed_env, proc.stdout, proc.stderr)
            assert "seed ok" in proc.stdout
    finally:
        os.remove(copy)
