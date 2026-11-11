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


def _plant_seq_claim(
    state_dir: Path,
    seq: int,
    *,
    claimed_at: datetime | None = None,
) -> None:
    seq_dir = state_dir / "seq"
    seq_dir.mkdir(parents=True, exist_ok=True)
    claim = seq_dir / f"{seq}.json"
    when = claimed_at or datetime.now(timezone.utc)
    claim.write_text(
        json.dumps({"seq": seq, "claimed_at": when.isoformat()}, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _plant_completed_tick(
    state_dir: Path,
    *,
    tick_id: str,
    completed_at: datetime,
    last_alert_ok: bool | None = True,
    seq: int = 1,
    write_seq_claim: bool = True,
    claimed_at: datetime | None = None,
) -> None:
    started = completed_at - timedelta(minutes=1)
    payload: dict = {
        "tick_id": tick_id,
        "seq": seq,
        "status": "completed",
        "noop": False,
        "overlap": False,
        "started_at": started.isoformat(),
        "completed_at": completed_at.isoformat(),
    }
    if last_alert_ok is not None:
        payload["last_alert_ok"] = last_alert_ok
    ticks = state_dir / "ticks"
    ticks.mkdir(parents=True, exist_ok=True)
    (ticks / f"tick-{tick_id}.json").write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if write_seq_claim:
        _plant_seq_claim(state_dir, seq, claimed_at=claimed_at or completed_at)


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
    assert verdict.reason.startswith("no_valid_completed_tick")


def test_deadman_last_alert_ok_false_alerts(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    completed = now - timedelta(minutes=5)
    _plant_completed_tick(
        tmp_path, tick_id="bad-alert", completed_at=completed, last_alert_ok=False
    )
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is False
    assert verdict.reason == "last_alert_ok_false"


@pytest.mark.parametrize(
    "field_value",
    ["missing", "string_false", "zero", "null"],
)
def test_deadman_last_alert_ok_not_exact_true_alerts(
    tmp_path: Path, field_value: str
) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    completed = now - timedelta(minutes=1)
    ticks = tmp_path / "ticks"
    ticks.mkdir(parents=True)
    _plant_seq_claim(tmp_path, 1)
    payload = {
        "tick_id": "flag",
        "seq": 1,
        "status": "completed",
        "noop": False,
        "overlap": False,
        "started_at": (completed - timedelta(minutes=1)).isoformat(),
        "completed_at": completed.isoformat(),
    }
    if field_value == "missing":
        pass
    elif field_value == "string_false":
        payload["last_alert_ok"] = "false"
    elif field_value == "zero":
        payload["last_alert_ok"] = 0
    elif field_value == "null":
        payload["last_alert_ok"] = None
    (ticks / "tick-flag.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is False
    assert verdict.reason == "last_alert_ok_false"


def test_mutation_deadman_last_alert_ok_truthy_ok(tmp_path: Path, monkeypatch) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    completed = now - timedelta(minutes=1)
    ticks = tmp_path / "ticks"
    ticks.mkdir(parents=True)
    _plant_seq_claim(tmp_path, 1)
    payload = {
        "tick_id": "bad",
        "seq": 1,
        "status": "completed",
        "noop": False,
        "overlap": False,
        "started_at": (completed - timedelta(minutes=1)).isoformat(),
        "completed_at": completed.isoformat(),
        "last_alert_ok": 1,
    }
    (ticks / "tick-bad.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")

    def truthy_ok(latest: dict) -> bool:
        return bool(latest.get("last_alert_ok"))

    monkeypatch.setattr(deadman, "_last_alert_ok_passes", truthy_ok)
    broken = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert broken.ok is True

    monkeypatch.undo()
    fixed = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert fixed.ok is False


def test_deadman_junk_files_skipped_good_tick_ok(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    completed = now - timedelta(minutes=1)
    _plant_completed_tick(tmp_path, tick_id="good", completed_at=completed, seq=2)
    ticks = tmp_path / "ticks"
    (ticks / "tick-utf8.json").write_bytes(b"\xff\xfe not utf8\n")
    big_digits = "9" * 5001
    (ticks / "tick-huge.json").write_text(
        '{"tick_id": "huge", "seq": ' + big_digits + ', "status": "completed"}\n',
        encoding="utf-8",
    )
    deep = "[" + ("[]" * 100_000) + "]"
    (ticks / "tick-deep.json").write_text(deep, encoding="utf-8")
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is True


def test_deadman_cli_junk_files_exit_zero_not_alert(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _plant_completed_tick(tmp_path, tick_id="good", completed_at=now - timedelta(minutes=1))
    ticks = tmp_path / "ticks"
    (ticks / "tick-utf8.json").write_bytes(b"\xff\xfe\n")
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    proc = subprocess.run(
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
    assert proc.returncode == 0
    assert proc.stderr == ""


def test_deadman_cli_unexpected_error_exit_3(tmp_path: Path, monkeypatch) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("simulated dead-man bug")

    monkeypatch.setattr(deadman, "evaluate_deadman", boom)
    import io

    cap = io.StringIO()
    monkeypatch.setattr(sys, "stdout", cap)
    code = deadman.main(["--state-dir", str(tmp_path)])
    assert code == 3
    assert cap.getvalue().strip() == "deadman_error:RuntimeError"


@pytest.mark.parametrize(
    ("max_age_min", "age_seconds", "expect_ok"),
    [
        (40, 40 * 60 - 1, True),
        (40, 40 * 60, True),
        (40, 40 * 60 + 1, False),
        (10, 10 * 60 - 1, True),
        (10, 10 * 60, True),
        (10, 10 * 60 + 1, False),
    ],
)
def test_deadman_age_boundary_seconds(
    tmp_path: Path, max_age_min: int, age_seconds: int, expect_ok: bool
) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    completed = now - timedelta(seconds=age_seconds)
    _plant_completed_tick(tmp_path, tick_id="edge", completed_at=completed)
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=max_age_min, now=now)
    assert verdict.ok is expect_ok


def test_mutation_deadman_age_uses_gte_not_gt(tmp_path: Path, monkeypatch) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    completed = now - timedelta(seconds=40 * 60)
    _plant_completed_tick(tmp_path, tick_id="edge", completed_at=completed)

    def stale_at_boundary(age: timedelta, limit: timedelta) -> bool:
        return age >= limit

    monkeypatch.setattr(deadman, "_age_exceeds_limit", stale_at_boundary)
    broken = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert broken.ok is False

    monkeypatch.undo()
    fixed = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert fixed.ok is True


def test_deadman_cli_max_age_min_10_boundary(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    completed = now - timedelta(seconds=10 * 60 + 1)
    _plant_completed_tick(tmp_path, tick_id="stale10", completed_at=completed)
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
    assert "stale" in proc.stdout


def test_deadman_higher_seq_older_tick_no_false_alarm(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _plant_completed_tick(
        tmp_path,
        tick_id="fresh",
        completed_at=now - timedelta(minutes=1),
        seq=5,
    )
    _plant_completed_tick(
        tmp_path,
        tick_id="stale-high-seq",
        completed_at=now - timedelta(days=3),
        seq=6,
        claimed_at=now - timedelta(minutes=1),
    )
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is True


def test_deadman_planted_high_seq_without_claim_does_not_hide_stale(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _plant_completed_tick(
        tmp_path,
        tick_id="real-stale",
        completed_at=now - timedelta(hours=5),
        seq=3,
    )
    _plant_completed_tick(
        tmp_path,
        tick_id="forged-fresh",
        completed_at=now - timedelta(minutes=1),
        seq=1_000_000,
        write_seq_claim=False,
    )
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is False
    assert "stale" in verdict.reason


def test_mutation_deadman_picks_highest_seq_not_latest_completed(
    tmp_path: Path, monkeypatch
) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _plant_completed_tick(
        tmp_path,
        tick_id="fresh",
        completed_at=now - timedelta(minutes=1),
        seq=5,
    )
    _plant_completed_tick(
        tmp_path,
        tick_id="stale-high-seq",
        completed_at=now - timedelta(days=3),
        seq=6,
        claimed_at=now - timedelta(minutes=1),
    )

    def by_seq(ticks: list[dict]) -> dict | None:
        if not ticks:
            return None
        return max(ticks, key=lambda t: int(t["seq"]))

    monkeypatch.setattr(deadman, "_select_latest_tick_by_completed_at", by_seq)
    broken = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert broken.ok is False

    monkeypatch.undo()
    fixed = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert fixed.ok is True


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

    _plant_completed_tick(
        tmp_path,
        tick_id="fresh-cli",
        completed_at=now - timedelta(minutes=1),
        seq=2,
    )
    ok = subprocess.run(
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
    assert ok.returncode == 0
    assert ok.stdout.strip() == "ok"


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


def test_deadman_forged_fresh_tick_invalid_claim_not_all_clear(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _plant_completed_tick(
        tmp_path,
        tick_id="real-stale",
        completed_at=now - timedelta(hours=5),
        seq=1,
        claimed_at=now - timedelta(hours=5),
    )
    forged_completed = now - timedelta(minutes=1)
    _plant_completed_tick(
        tmp_path,
        tick_id="forged-fresh",
        completed_at=forged_completed,
        seq=1_000_000,
        write_seq_claim=False,
    )
    (tmp_path / "seq" / "1000000.json").write_text("not json\n", encoding="utf-8")
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is False
    assert "stale" in verdict.reason


def test_mutation_deadman_accepts_tick_when_claim_file_exists_only(
    tmp_path: Path, monkeypatch
) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _plant_completed_tick(
        tmp_path,
        tick_id="real-stale",
        completed_at=now - timedelta(hours=5),
        seq=1,
        claimed_at=now - timedelta(minutes=2),
    )
    _plant_completed_tick(
        tmp_path,
        tick_id="forged-fresh",
        completed_at=now - timedelta(minutes=1),
        seq=1_000_000,
        write_seq_claim=False,
    )
    (tmp_path / "seq" / "1000000.json").write_text("not json\n", encoding="utf-8")

    def claim_exists_only(state_dir: Path, seq: int) -> bool:
        return (state_dir / "seq" / f"{seq}.json").is_file()

    monkeypatch.setattr(deadman, "_seq_claim_valid", claim_exists_only)
    broken = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert broken.ok is True

    monkeypatch.undo()
    fixed = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert fixed.ok is False


def test_deadman_equal_completed_at_bad_last_alert_ok_alerts(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    at = now - timedelta(minutes=1)
    _plant_completed_tick(tmp_path, tick_id="a", completed_at=at, seq=1)
    _plant_completed_tick(tmp_path, tick_id="z", completed_at=at, seq=2, last_alert_ok=False)
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is False
    assert verdict.reason == "last_alert_ok_false"


def test_mutation_deadman_equal_time_keeps_first_filename_wins(
    tmp_path: Path, monkeypatch
) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    at = now - timedelta(minutes=1)
    _plant_completed_tick(tmp_path, tick_id="a", completed_at=at, seq=1)
    _plant_completed_tick(tmp_path, tick_id="z", completed_at=at, seq=2, last_alert_ok=False)

    def first_wins(ticks: list[dict]) -> dict | None:
        best = None
        best_at = None
        for tick in ticks:
            from tools.review_orchestrator.persist import _parse_utc_iso

            completed = _parse_utc_iso(tick.get("completed_at"))
            if completed is None:
                continue
            if best_at is None or completed > best_at:
                best_at = completed
                best = tick
        return best

    monkeypatch.setattr(deadman, "_select_latest_tick_by_completed_at", first_wins)
    broken = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert broken.ok is True

    monkeypatch.undo()
    fixed = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert fixed.ok is False


def test_deadman_oversized_tick_file_skipped(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    completed = now - timedelta(minutes=1)
    _plant_completed_tick(tmp_path, tick_id="good", completed_at=completed)
    ticks = tmp_path / "ticks"
    oversized = "x" * (deadman.TICK_FILE_MAX_BYTES + 1)
    (ticks / "tick-huge.json").write_text(oversized, encoding="utf-8")
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is True


def test_mutation_deadman_reads_unbounded_tick_file(tmp_path: Path, monkeypatch) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    completed = now - timedelta(minutes=1)
    _plant_completed_tick(tmp_path, tick_id="good", completed_at=completed)

    monkeypatch.setattr(deadman, "TICK_FILE_MAX_BYTES", 0)
    broken = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert broken.ok is False

    monkeypatch.undo()
    fixed = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert fixed.ok is True


def test_deadman_corrupt_newest_tick_alerts_despite_older_valid(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _plant_completed_tick(
        tmp_path,
        tick_id="old_ok",
        completed_at=now - timedelta(minutes=30),
        seq=1,
    )
    _plant_seq_claim(tmp_path, 2, claimed_at=now - timedelta(minutes=50))
    ticks = tmp_path / "ticks"
    (ticks / "tick-new_bad.json").write_bytes(b"\xff\xfe not utf8\n")
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is False
    assert "attempt" in verdict.reason or "stale" in verdict.reason


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
    assert "max-age-min" in proc.stderr.lower() or "0" in proc.stderr


def test_deadman_cli_rejects_max_age_min_400(tmp_path: Path) -> None:
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.review_orchestrator.deadman",
            "--state-dir",
            str(tmp_path),
            "--max-age-min",
            "400",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_REPO_ROOT),
    )
    assert proc.returncode == 2


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
