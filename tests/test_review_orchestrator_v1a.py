"""v1a dead-man contract tests (behavior, not implementation)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import tools.review_orchestrator.deadman as deadman
from tools.review_orchestrator.persist import run_tick

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _plant_completed_tick(
    state_dir: Path,
    *,
    tick_id: str,
    completed_at: datetime,
    last_alert_ok: bool = True,
    seq: int = 1,
) -> None:
    started = completed_at - timedelta(minutes=1)
    payload = {
        "tick_id": tick_id,
        "seq": seq,
        "status": "completed",
        "noop": False,
        "overlap": False,
        "started_at": started.isoformat(),
        "completed_at": completed_at.isoformat(),
        "last_alert_ok": last_alert_ok,
    }
    ticks = state_dir / "ticks"
    ticks.mkdir(parents=True, exist_ok=True)
    (ticks / f"tick-{tick_id}.json").write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_tick_write_includes_last_alert_ok_true(tmp_path: Path) -> None:
    result = run_tick(tmp_path, tick_id="v1", noop=False)
    data = json.loads(result.path.read_text(encoding="utf-8"))
    assert data.get("last_alert_ok") is True


def test_deadman_fresh_tick_ok(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    completed = now - timedelta(minutes=1)
    _plant_completed_tick(tmp_path, tick_id="fresh", completed_at=completed)
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is True
    assert verdict.reason == "ok"


def test_deadman_stale_41_minutes_alerts(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    completed = now - timedelta(minutes=41)
    _plant_completed_tick(tmp_path, tick_id="old", completed_at=completed)
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is False
    assert "stale" in verdict.reason


def test_deadman_empty_dir_alerts(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is False
    assert verdict.reason == "no_valid_completed_tick"


def test_deadman_last_alert_ok_false_alerts(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    completed = now - timedelta(minutes=5)
    _plant_completed_tick(
        tmp_path, tick_id="bad-alert", completed_at=completed, last_alert_ok=False
    )
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is False
    assert verdict.reason == "last_alert_ok_false"


def test_deadman_missing_last_alert_ok_defaults_ok(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    completed = now - timedelta(minutes=5)
    ticks = tmp_path / "ticks"
    ticks.mkdir(parents=True)
    payload = {
        "tick_id": "legacy",
        "seq": 1,
        "status": "completed",
        "noop": False,
        "overlap": False,
        "started_at": (completed - timedelta(minutes=1)).isoformat(),
        "completed_at": completed.isoformat(),
    }
    (ticks / "tick-legacy.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is True


def test_deadman_malformed_ticks_no_crash(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    ticks = tmp_path / "ticks"
    ticks.mkdir(parents=True)
    (ticks / "tick-bad.json").write_text("not json\n", encoding="utf-8")
    (ticks / "planted.json.tmp").write_text("{}\n", encoding="utf-8")
    completed = now - timedelta(minutes=1)
    _plant_completed_tick(tmp_path, tick_id="good", completed_at=completed, seq=2)
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is True


def test_deadman_cli_exit_codes(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    completed = now - timedelta(minutes=41)
    _plant_completed_tick(tmp_path, tick_id="stale", completed_at=completed)
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    alert = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.review_orchestrator.deadman",
            "--state-dir",
            str(tmp_path),
            "--max-age-min",
            "40",
            "--now",
            now.isoformat(),
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_REPO_ROOT),
    )
    assert alert.returncode == 1
    assert alert.stdout.strip()

    run_tick(tmp_path, tick_id="fresh-cli", noop=False)
    ok = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.review_orchestrator.deadman",
            "--state-dir",
            str(tmp_path),
            "--max-age-min",
            "40",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_REPO_ROOT),
    )
    assert ok.returncode == 0
    assert ok.stdout.strip() == "ok"


def test_mutation_deadman_never_alerts_on_stale(tmp_path: Path, monkeypatch) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    completed = now - timedelta(minutes=41)
    _plant_completed_tick(tmp_path, tick_id="old", completed_at=completed)

    def always_ok(state_dir: Path, *, max_age_minutes: int = 40, now=None):
        return deadman.DeadmanVerdict(ok=True, reason="ok")

    monkeypatch.setattr(deadman, "evaluate_deadman", always_ok)
    broken = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert broken.ok is True

    monkeypatch.undo()
    fixed = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert fixed.ok is False


def test_mutation_deadman_alerts_on_fresh(tmp_path: Path, monkeypatch) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    completed = now - timedelta(minutes=1)
    _plant_completed_tick(tmp_path, tick_id="fresh", completed_at=completed)

    monkeypatch.setattr(
        deadman,
        "evaluate_deadman",
        lambda *_a, **_k: deadman.DeadmanVerdict(ok=False, reason="forced_alert"),
    )
    broken = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert broken.ok is False

    monkeypatch.undo()
    fixed = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert fixed.ok is True


def test_mutation_deadman_ignores_last_alert_ok(tmp_path: Path, monkeypatch) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    completed = now - timedelta(minutes=1)
    _plant_completed_tick(
        tmp_path, tick_id="bad", completed_at=completed, last_alert_ok=False
    )

    def skip_flag(state_dir: Path, *, max_age_minutes: int = 40, now=None):
        from tools.review_orchestrator.persist import read_newest_completed_tick_report

        report = read_newest_completed_tick_report(state_dir, now=now)
        if report.tick is None:
            return deadman.DeadmanVerdict(ok=False, reason="no_valid_completed_tick")
        return deadman.DeadmanVerdict(ok=True, reason="ok")

    monkeypatch.setattr(deadman, "evaluate_deadman", skip_flag)
    broken = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert broken.ok is True

    monkeypatch.undo()
    fixed = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert fixed.ok is False


def test_mutation_deadman_empty_dir_ok(tmp_path: Path, monkeypatch) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(
        deadman,
        "evaluate_deadman",
        lambda *_a, **_k: deadman.DeadmanVerdict(ok=True, reason="ok"),
    )
    broken = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert broken.ok is True

    monkeypatch.undo()
    fixed = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert fixed.ok is False


def test_exam_v1a_state_dir_parent_is_rerunnable(tmp_path: Path) -> None:
    parent = tmp_path / "real-store"
    parent.mkdir()
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    cmd = [
        sys.executable,
        "-m",
        "tools.review_orchestrator.exam_v1a",
        "--state-dir",
        str(parent),
    ]
    for _ in range(2):
        subprocess.run(cmd, check=True, env=env, cwd=str(_REPO_ROOT))
    assert list(parent.iterdir()) == []


def test_exam_v1a_under_python_O(tmp_path: Path) -> None:
    parent = tmp_path / "store-o"
    parent.mkdir()
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    cmd = [
        sys.executable,
        "-O",
        "-m",
        "tools.review_orchestrator.exam_v1a",
        "--state-dir",
        str(parent),
    ]
    subprocess.run(cmd, check=True, env=env, cwd=str(_REPO_ROOT))
