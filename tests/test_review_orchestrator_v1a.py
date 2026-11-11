"""v1a dead-man: heartbeat/latest.json only."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import tools.review_orchestrator.deadman as deadman
from tools.review_orchestrator.persist import _write_tick_atomically, run_tick

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_heartbeat(
    state_dir: Path,
    *,
    tick_id: str = "hb",
    attempt_at: datetime,
    completed_at: datetime,
    last_alert_ok: bool = True,
) -> None:
    _write_tick_atomically(
        state_dir / "heartbeat" / "latest.json",
        {
            "tick_id": tick_id,
            "attempt_at": attempt_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "last_alert_ok": last_alert_ok,
        },
    )


def test_run_tick_writes_heartbeat(tmp_path: Path) -> None:
    result = run_tick(tmp_path, tick_id="v1", noop=False)
    hb_path = tmp_path / "heartbeat" / "latest.json"
    assert hb_path.is_file()
    data = json.loads(hb_path.read_text(encoding="utf-8"))
    assert data["tick_id"] == "v1"
    assert data.get("last_alert_ok") is True
    tick = json.loads(result.path.read_text(encoding="utf-8"))
    assert data["completed_at"] == tick["completed_at"]


def test_deadman_fresh_heartbeat_ok(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    at = now - timedelta(minutes=1)
    _write_heartbeat(tmp_path, attempt_at=at, completed_at=at)
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is True
    assert verdict.reason == "ok"


def test_deadman_missing_heartbeat_unreadable(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is False
    assert verdict.reason == "heartbeat_unreadable"


def test_mutation_deadman_missing_heartbeat_ok(tmp_path: Path, monkeypatch) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    at = now - timedelta(minutes=1)

    def fake_load(_sd: Path) -> dict:
        return {
            "tick_id": "fake",
            "attempt_at": at.isoformat(),
            "completed_at": at.isoformat(),
            "last_alert_ok": True,
        }

    monkeypatch.setattr(deadman, "_load_heartbeat", fake_load)
    broken = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert broken.ok is True

    monkeypatch.undo()
    fixed = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert fixed.ok is False


def test_deadman_garbage_json_unreadable(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    path = tmp_path / "heartbeat"
    path.mkdir(parents=True)
    (path / "latest.json").write_text("{not json\n", encoding="utf-8")
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.reason == "heartbeat_unreadable"


def test_mutation_deadman_accepts_garbage_json(tmp_path: Path, monkeypatch) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    at = now - timedelta(minutes=1)
    path = tmp_path / "heartbeat"
    path.mkdir(parents=True)
    (path / "latest.json").write_text("{not json\n", encoding="utf-8")

    def fake_load(_sd: Path) -> dict:
        return {
            "tick_id": "x",
            "attempt_at": at.isoformat(),
            "completed_at": at.isoformat(),
            "last_alert_ok": True,
        }

    monkeypatch.setattr(deadman, "_load_heartbeat", fake_load)
    broken = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert broken.ok is True

    monkeypatch.undo()
    fixed = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert fixed.reason == "heartbeat_unreadable"


def test_deadman_oversized_heartbeat_unreadable(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    path = tmp_path / "heartbeat"
    path.mkdir(parents=True)
    (path / "latest.json").write_bytes(b"x" * (deadman.HEARTBEAT_FILE_MAX_BYTES + 1))
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.reason == "heartbeat_unreadable"


def test_mutation_deadman_oversized_read_allowed(tmp_path: Path, monkeypatch) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    at = now - timedelta(minutes=1)
    path = tmp_path / "heartbeat"
    path.mkdir(parents=True)
    huge = {
        "tick_id": "big",
        "attempt_at": at.isoformat(),
        "completed_at": at.isoformat(),
        "last_alert_ok": True,
        "pad": "z" * (deadman.HEARTBEAT_FILE_MAX_BYTES - 120),
    }
    body = json.dumps(huge) + "\n"
    assert len(body.encode()) > deadman.HEARTBEAT_FILE_MAX_BYTES
    (path / "latest.json").write_text(body, encoding="utf-8")

    monkeypatch.setattr(deadman, "HEARTBEAT_FILE_MAX_BYTES", 10**9)
    broken = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert broken.ok is True

    monkeypatch.undo()
    fixed = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert fixed.reason == "heartbeat_unreadable"


def test_deadman_future_attempt_at_alerts(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _write_heartbeat(
        tmp_path,
        attempt_at=now + timedelta(minutes=6),
        completed_at=now - timedelta(minutes=1),
    )
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.reason == "heartbeat_future"


def test_deadman_future_completed_at_alerts(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    at = now - timedelta(minutes=1)
    _write_heartbeat(
        tmp_path,
        attempt_at=at,
        completed_at=now + timedelta(minutes=6),
    )
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.reason == "heartbeat_future"


def test_mutation_deadman_ignores_future_attempt(tmp_path: Path, monkeypatch) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _write_heartbeat(
        tmp_path,
        attempt_at=now + timedelta(minutes=6),
        completed_at=now - timedelta(minutes=1),
    )
    monkeypatch.setattr(deadman, "_is_future", lambda _ts, _ref: False)
    broken = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert broken.ok is True

    monkeypatch.undo()
    fixed = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert fixed.reason == "heartbeat_future"


def test_deadman_attempt_stale_41m(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _write_heartbeat(
        tmp_path,
        attempt_at=now - timedelta(minutes=41),
        completed_at=now - timedelta(minutes=1),
    )
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.reason == "attempt_stale"


def test_mutation_deadman_attempt_stale_uses_gte(tmp_path: Path, monkeypatch) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _write_heartbeat(
        tmp_path,
        attempt_at=now - timedelta(seconds=40 * 60),
        completed_at=now - timedelta(minutes=1),
    )

    def stale_gte(age: timedelta, limit: timedelta) -> bool:
        return age >= limit

    monkeypatch.setattr(deadman, "_is_stale", stale_gte)
    broken = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert broken.reason == "attempt_stale"

    monkeypatch.undo()
    fixed = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert fixed.ok is True


def test_deadman_completed_stale_41m(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    at = now - timedelta(minutes=1)
    _write_heartbeat(tmp_path, attempt_at=at, completed_at=now - timedelta(minutes=41))
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.reason == "completed_stale"


def test_mutation_deadman_completed_stale_uses_gte(tmp_path: Path, monkeypatch) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    at = now - timedelta(minutes=1)
    _write_heartbeat(
        tmp_path, attempt_at=at, completed_at=now - timedelta(seconds=40 * 60)
    )

    real = deadman._is_stale

    def stale_completed_only(age: timedelta, limit: timedelta) -> bool:
        return age >= limit

    monkeypatch.setattr(deadman, "_is_stale", stale_completed_only)
    broken = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert broken.reason == "completed_stale"

    monkeypatch.undo()
    fixed = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert fixed.ok is True


@pytest.mark.parametrize(
    ("field", "age_seconds", "expect_ok"),
    [
        ("attempt_at", 40 * 60 - 1, True),
        ("attempt_at", 40 * 60, True),
        ("attempt_at", 40 * 60 + 1, False),
        ("completed_at", 40 * 60 - 1, True),
        ("completed_at", 40 * 60, True),
        ("completed_at", 40 * 60 + 1, False),
    ],
)
def test_deadman_age_boundary_seconds(
    tmp_path: Path, field: str, age_seconds: int, expect_ok: bool
) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    fresh = now - timedelta(minutes=1)
    edge = now - timedelta(seconds=age_seconds)
    if field == "attempt_at":
        _write_heartbeat(tmp_path, attempt_at=edge, completed_at=fresh)
    else:
        _write_heartbeat(tmp_path, attempt_at=fresh, completed_at=edge)
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is expect_ok


@pytest.mark.parametrize(
    ("flag",),
    [("false",), ("zero",), ("null",), ("missing_type",)],
)
def test_deadman_last_alert_failed(tmp_path: Path, flag: str) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    at = now - timedelta(minutes=1)
    path = tmp_path / "heartbeat"
    path.mkdir(parents=True)
    payload: dict = {
        "tick_id": "flag",
        "attempt_at": at.isoformat(),
        "completed_at": at.isoformat(),
    }
    if flag == "false":
        payload["last_alert_ok"] = False
    elif flag == "zero":
        payload["last_alert_ok"] = 0  # type: ignore[assignment]
    elif flag == "null":
        payload["last_alert_ok"] = None  # type: ignore[assignment]
    else:
        payload["last_alert_ok"] = "no"  # type: ignore[assignment]
    _write_tick_atomically(path / "latest.json", payload)
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    if flag == "false":
        assert verdict.reason == "last_alert_failed"
    else:
        assert verdict.reason == "heartbeat_unreadable"


def test_mutation_deadman_last_alert_truthy_ok(tmp_path: Path, monkeypatch) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    at = now - timedelta(minutes=1)
    path = tmp_path / "heartbeat"
    path.mkdir(parents=True)
    _write_tick_atomically(
        path / "latest.json",
        {
            "tick_id": "x",
            "attempt_at": at.isoformat(),
            "completed_at": at.isoformat(),
            "last_alert_ok": 1,  # invalid type, unreadable
        },
    )

    real_parse = deadman._parse_heartbeat_record

    def coerce_bool(raw: object) -> dict | None:
        if isinstance(raw, dict):
            raw = dict(raw)
            if not isinstance(raw.get("last_alert_ok"), bool):
                raw["last_alert_ok"] = bool(raw.get("last_alert_ok"))
        return real_parse(raw)

    monkeypatch.setattr(deadman, "_parse_heartbeat_record", coerce_bool)
    broken = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert broken.ok is True

    monkeypatch.undo()
    fixed = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert fixed.reason == "heartbeat_unreadable"


def test_deadman_cli_unexpected_error_exit_3(tmp_path: Path, monkeypatch) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("simulated")

    monkeypatch.setattr(deadman, "evaluate_deadman", boom)
    import io

    cap = io.StringIO()
    monkeypatch.setattr(sys, "stdout", cap)
    code = deadman.main(["--state-dir", str(tmp_path)])
    assert code == 3
    assert cap.getvalue().strip() == "deadman_error:RuntimeError"


def test_deadman_cli_rejects_max_age_min_zero(tmp_path: Path) -> None:
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.review_orchestrator.deadman",
            "--state-dir",
            str(tmp_path),
            "--max-age-min",
            "0",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_REPO_ROOT),
    )
    assert proc.returncode == 2


def test_deadman_cli_max_age_min_10_boundary(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _write_heartbeat(
        tmp_path,
        attempt_at=now - timedelta(minutes=1),
        completed_at=now - timedelta(seconds=10 * 60 + 1),
    )
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.review_orchestrator.deadman",
            "--state-dir",
            str(tmp_path),
            "--max-age-min",
            "10",
            "--now",
            now.isoformat(),
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_REPO_ROOT),
    )
    assert proc.returncode == 1
    assert proc.stdout.strip() == "completed_stale"


def test_deadman_ignores_tick_files_in_store(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _write_heartbeat(tmp_path, attempt_at=now - timedelta(minutes=1), completed_at=now - timedelta(minutes=1))
    ticks = tmp_path / "ticks"
    ticks.mkdir(parents=True)
    (ticks / "tick-forged.json").write_text(
        json.dumps(
            {
                "tick_id": "forged",
                "seq": 999,
                "status": "completed",
                "completed_at": (now - timedelta(hours=9)).isoformat(),
                "started_at": (now - timedelta(hours=9)).isoformat(),
                "last_alert_ok": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is True


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
