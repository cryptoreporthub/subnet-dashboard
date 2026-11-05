"""Cross-process domain write gate (Design A)."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time

import pytest

from internal.store.domain_write_gate import WriteTicket, commit, mint_ticket, revoke


def test_predictions_commit_succeeds_without_interference(tmp_path, monkeypatch):
    epoch_path = str(tmp_path / "predictions.epoch")
    monkeypatch.setenv("PREDICTIONS_EPOCH_PATH", epoch_path)
    monkeypatch.setenv("PREDICTIONS_LOCK_PATH", str(tmp_path / "predictions.lock"))
    ticket = mint_ticket("predictions", "solo")
    ok_holder = {"ok": False}

    def _body() -> None:
        ok_holder["ok"] = True

    assert commit(ticket, _body) is True
    assert ok_holder["ok"] is True


@pytest.mark.no_persist_gate
def test_predictions_commit_loses_race_when_epoch_revoked_in_other_process(tmp_path, monkeypatch):
    """Subprocess revokes epoch, then sibling commit with stale ticket fails (cross-process)."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    epoch_path = str(tmp_path / "predictions.epoch")
    lock_path = str(tmp_path / "predictions.lock")
    result_path = str(tmp_path / "result.txt")
    monkeypatch.setenv("PREDICTIONS_EPOCH_PATH", epoch_path)
    monkeypatch.setenv("PREDICTIONS_LOCK_PATH", lock_path)
    env = os.environ.copy()
    env["PYTHONPATH"] = repo_root

    ticket = mint_ticket("predictions", "race-parent")
    revoke_script = textwrap.dedent(
        """
        from internal.store.domain_write_gate import revoke
        revoke("predictions", reason="child-race")
        """
    )
    commit_script = textwrap.dedent(
        f"""
        from internal.store.domain_write_gate import WriteTicket, commit
        ticket = WriteTicket("predictions", {ticket.epoch}, {ticket.run_id!r})
        ok = commit(ticket, lambda: None)
        with open({result_path!r}, "w", encoding="utf-8") as handle:
            handle.write("1" if ok else "0")
        """
    )
    assert (
        subprocess.run(
            [sys.executable, "-c", revoke_script],
            env=env,
            cwd=repo_root,
            check=False,
        ).returncode
        == 0
    )
    assert (
        subprocess.run(
            [sys.executable, "-c", commit_script],
            env=env,
            cwd=repo_root,
            check=False,
        ).returncode
        == 0
    )
    assert open(result_path, encoding="utf-8").read() == "0"


def test_predictions_commit_refused_after_revoke_same_process(tmp_path, monkeypatch):
    monkeypatch.setenv("PREDICTIONS_EPOCH_PATH", str(tmp_path / "predictions.epoch"))
    monkeypatch.setenv("PREDICTIONS_LOCK_PATH", str(tmp_path / "predictions.lock"))
    ticket = mint_ticket("predictions", "stale")
    revoke("predictions", reason="test-revoke")
    assert commit(ticket, lambda: None) is False
