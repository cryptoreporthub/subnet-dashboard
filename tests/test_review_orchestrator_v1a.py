"""v1a dead-man: heartbeat/latest.json only."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import tools.review_orchestrator.deadman as deadman
import tools.review_orchestrator.persist as persist
from tools.review_orchestrator.persist import _write_tick_atomically, run_tick

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_heartbeat(
    state_dir: Path,
    *,
    tick_id: str = "hb",
    attempt_at: datetime,
    completed_at: datetime,
    last_alert_ok: bool | None = None,
) -> None:
    payload: dict = {
        "tick_id": tick_id,
        "attempt_at": attempt_at.isoformat(),
        "completed_at": completed_at.isoformat(),
    }
    if last_alert_ok is not None:
        payload["last_alert_ok"] = last_alert_ok
    _write_tick_atomically(state_dir / "heartbeat" / "latest.json", payload)


def test_run_tick_writes_heartbeat(tmp_path: Path) -> None:
    result = run_tick(tmp_path, tick_id="v1", noop=False)
    hb_path = tmp_path / "heartbeat" / "latest.json"
    assert hb_path.is_file()
    data = json.loads(hb_path.read_text(encoding="utf-8"))
    assert data["tick_id"] == "v1"
    assert "last_alert_ok" not in data
    tick = json.loads(result.path.read_text(encoding="utf-8"))
    assert data["attempt_at"] == tick["started_at"]
    assert data["completed_at"] == tick["completed_at"]
    assert "last_alert_ok" not in tick


def test_heartbeat_monotonic_publish_rejects_older_after_newer(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    newer = {
        "tick_id": "new",
        "attempt_at": (now - timedelta(minutes=2)).isoformat(),
        "completed_at": (now - timedelta(minutes=1)).isoformat(),
    }
    older = {
        "tick_id": "old",
        "attempt_at": (now - timedelta(minutes=50)).isoformat(),
        "completed_at": (now - timedelta(minutes=49)).isoformat(),
    }
    persist._publish_heartbeat_monotonic(tmp_path, newer)
    persist._publish_heartbeat_monotonic(tmp_path, older)
    data = json.loads(
        (tmp_path / "heartbeat" / "latest.json").read_text(encoding="utf-8")
    )
    assert data["tick_id"] == "new"
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is True


def test_mutation_heartbeat_beats_guard_removed(tmp_path: Path, monkeypatch) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    newer = {
        "tick_id": "new",
        "attempt_at": (now - timedelta(minutes=2)).isoformat(),
        "completed_at": (now - timedelta(minutes=1)).isoformat(),
    }
    older = {
        "tick_id": "old",
        "attempt_at": (now - timedelta(minutes=50)).isoformat(),
        "completed_at": (now - timedelta(minutes=49)).isoformat(),
    }

    monkeypatch.setattr(persist, "_heartbeat_beats", lambda _i, _c: True)
    persist._publish_heartbeat_monotonic(tmp_path, newer)
    persist._publish_heartbeat_monotonic(tmp_path, older)
    broken = json.loads(
        (tmp_path / "heartbeat" / "latest.json").read_text(encoding="utf-8")
    )
    assert broken["tick_id"] == "old"
    broken_verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert broken_verdict.reason == "attempt_stale"

    monkeypatch.undo()
    (tmp_path / "heartbeat" / "latest.json").unlink()
    persist._publish_heartbeat_monotonic(tmp_path, newer)
    persist._publish_heartbeat_monotonic(tmp_path, older)
    fixed = json.loads(
        (tmp_path / "heartbeat" / "latest.json").read_text(encoding="utf-8")
    )
    assert fixed["tick_id"] == "new"
    assert deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now).ok is True


def test_run_tick_delayed_older_heartbeat_publish_preserves_newer(
    tmp_path: Path, monkeypatch
) -> None:
    newer_published = threading.Event()
    real_publish = persist._publish_heartbeat_monotonic

    def gated_publish(state_dir: Path, payload: dict) -> None:
        if payload.get("tick_id") == "old":
            assert newer_published.wait(timeout=2.0)
            real_publish(state_dir, payload)
        else:
            real_publish(state_dir, payload)
            newer_published.set()

    monkeypatch.setattr(persist, "_publish_heartbeat_monotonic", gated_publish)

    errors: list[BaseException] = []

    def slow_old_tick() -> None:
        try:
            run_tick(tmp_path, tick_id="old", noop=True)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    worker = threading.Thread(target=slow_old_tick, name="slow-old-tick")
    worker.start()
    newer = run_tick(tmp_path, tick_id="new", noop=True)
    worker.join(timeout=5.0)
    assert not worker.is_alive()
    assert not errors

    completed = persist._parse_utc_iso(
        json.loads(newer.path.read_text(encoding="utf-8"))["completed_at"]
    )
    assert completed is not None
    data = json.loads(
        (tmp_path / "heartbeat" / "latest.json").read_text(encoding="utf-8")
    )
    assert data["tick_id"] == "new"
    assert deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=completed).ok is True


def test_run_tick_tick_write_failure_leaves_heartbeat_unchanged(
    tmp_path: Path, monkeypatch
) -> None:
    at = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _write_heartbeat(tmp_path, tick_id="prev", attempt_at=at, completed_at=at)
    before = (tmp_path / "heartbeat" / "latest.json").read_text(encoding="utf-8")
    real_write = persist._write_tick_atomically

    def fail_tick_write(final: Path, payload: dict) -> None:
        if "heartbeat" not in str(final):
            raise OSError("simulated tick write failure")
        real_write(final, payload)

    monkeypatch.setattr(persist, "_write_tick_atomically", fail_tick_write)
    with pytest.raises(OSError, match="simulated tick write failure"):
        run_tick(tmp_path, tick_id="fail", noop=False)
    assert (tmp_path / "heartbeat" / "latest.json").read_text(encoding="utf-8") == before


def test_run_tick_heartbeat_write_failure_leaves_heartbeat_unchanged(
    tmp_path: Path, monkeypatch
) -> None:
    at = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _write_heartbeat(tmp_path, tick_id="prev", attempt_at=at, completed_at=at)
    before = (tmp_path / "heartbeat" / "latest.json").read_text(encoding="utf-8")
    real_write = persist._write_tick_atomically

    def fail_heartbeat_write(final: Path, payload: dict) -> None:
        if "heartbeat" in str(final) and final.name == "latest.json":
            raise OSError("simulated heartbeat write failure")
        real_write(final, payload)

    monkeypatch.setattr(persist, "_write_tick_atomically", fail_heartbeat_write)
    with pytest.raises(OSError, match="simulated heartbeat write failure"):
        run_tick(tmp_path, tick_id="fail", noop=False)
    assert (tmp_path / "heartbeat" / "latest.json").read_text(encoding="utf-8") == before


def test_deadman_missing_last_alert_ok_ok(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    at = now - timedelta(minutes=1)
    _write_heartbeat(tmp_path, attempt_at=at, completed_at=at, last_alert_ok=None)
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is True


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


@pytest.mark.parametrize(
    ("offset", "expect_future"),
    [
        (timedelta(minutes=5), False),
        (timedelta(minutes=5, seconds=1), True),
    ],
)
def test_deadman_future_slack_boundary_on_attempt_at(
    tmp_path: Path, offset: timedelta, expect_future: bool
) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _write_heartbeat(
        tmp_path,
        attempt_at=now + offset,
        completed_at=now - timedelta(minutes=1),
    )
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    if expect_future:
        assert verdict.reason == "heartbeat_future"
    else:
        assert verdict.ok is True


def test_mutation_deadman_zero_future_slack_alerts(tmp_path: Path, monkeypatch) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _write_heartbeat(
        tmp_path,
        attempt_at=now + timedelta(seconds=1),
        completed_at=now - timedelta(minutes=1),
    )
    monkeypatch.setattr(deadman, "_FUTURE_SLACK", timedelta(0))
    broken = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert broken.reason == "heartbeat_future"

    monkeypatch.undo()
    fixed = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert fixed.ok is True


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


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"attempt_at": "2026-01-01T00:00:00+00:00", "completed_at": "2026-01-01T00:00:00+00:00"},
        {"tick_id": "", "attempt_at": "2026-01-01T00:00:00+00:00", "completed_at": "2026-01-01T00:00:00+00:00"},
    ],
)
def test_deadman_heartbeat_unreadable_missing_tick_id(
    tmp_path: Path, bad_payload: dict
) -> None:
    path = tmp_path / "heartbeat"
    path.mkdir(parents=True)
    _write_tick_atomically(path / "latest.json", bad_payload)
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.reason == "heartbeat_unreadable"


def test_deadman_heartbeat_unreadable_non_object_root(tmp_path: Path) -> None:
    path = tmp_path / "heartbeat"
    path.mkdir(parents=True)
    (path / "latest.json").write_text("[1, 2, 3]\n", encoding="utf-8")
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.reason == "heartbeat_unreadable"


def test_deadman_heartbeat_unreadable_bad_attempt_at_timestamp(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    path = tmp_path / "heartbeat"
    path.mkdir(parents=True)
    _write_tick_atomically(
        path / "latest.json",
        {
            "tick_id": "bad-ts",
            "attempt_at": "not-a-timestamp",
            "completed_at": (now - timedelta(minutes=1)).isoformat(),
        },
    )
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.reason == "heartbeat_unreadable"


def test_mutation_deadman_parse_drops_tick_id_check(
    tmp_path: Path, monkeypatch
) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    at = now - timedelta(minutes=1)
    path = tmp_path / "heartbeat"
    path.mkdir(parents=True)
    _write_tick_atomically(
        path / "latest.json",
        {"attempt_at": at.isoformat(), "completed_at": at.isoformat()},
    )

    real_parse = deadman._parse_heartbeat_record

    def lax_parse(raw: object) -> dict | None:
        if isinstance(raw, dict) and raw.get("attempt_at") and raw.get("completed_at"):
            return dict(raw, tick_id="invented")
        return real_parse(raw)

    monkeypatch.setattr(deadman, "_parse_heartbeat_record", lax_parse)
    broken = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert broken.ok is True

    monkeypatch.undo()
    assert deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now).reason == (
        "heartbeat_unreadable"
    )


def test_deadman_library_default_max_age_is_40_minutes(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _write_heartbeat(
        tmp_path,
        attempt_at=now - timedelta(minutes=41),
        completed_at=now - timedelta(minutes=1),
    )
    assert deadman.evaluate_deadman(tmp_path, now=now).reason == "attempt_stale"


def test_mutation_deadman_library_default_max_age(tmp_path: Path, monkeypatch) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _write_heartbeat(
        tmp_path,
        attempt_at=now - timedelta(minutes=15),
        completed_at=now - timedelta(minutes=1),
    )

    real = deadman.evaluate_deadman

    def broken_eval(
        state_dir: Path,
        *,
        max_age_minutes: int = 10,
        now: datetime | None = None,
    ) -> deadman.DeadmanVerdict:
        return real(state_dir, max_age_minutes=max_age_minutes, now=now)

    monkeypatch.setattr(deadman, "evaluate_deadman", broken_eval)
    assert deadman.evaluate_deadman(tmp_path, now=now).reason == "attempt_stale"

    monkeypatch.undo()
    assert deadman.evaluate_deadman(tmp_path, now=now).ok is True


def test_deadman_cli_default_max_age_40_minutes(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _write_heartbeat(
        tmp_path,
        attempt_at=now - timedelta(minutes=41),
        completed_at=now - timedelta(minutes=1),
    )
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.review_orchestrator.deadman",
            "--state-dir",
            str(tmp_path),
            "--now",
            now.isoformat(),
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_REPO_ROOT),
    )
    assert proc.returncode == 1
    assert proc.stdout.strip() == "attempt_stale"


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
