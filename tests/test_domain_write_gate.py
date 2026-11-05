"""Cross-process domain write gate (Design A)."""

from __future__ import annotations

import json
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


def test_predictions_stale_merge_refuses_and_preserves_disk_row(tmp_path, monkeypatch):
    from internal.learning import predictions_store as ps
    from internal.store.domain_write_gate import TicketRefused

    pred_path = tmp_path / "predictions.json"
    monkeypatch.setattr(ps, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setenv("PREDICTIONS_EPOCH_PATH", str(tmp_path / "predictions.epoch"))
    monkeypatch.setenv("PREDICTIONS_LOCK_PATH", str(tmp_path / "predictions.lock"))
    keep = {"id": "row-keep", "status": "resolved", "netuid": 3, "correct": True}
    pred_path.write_text(
        json.dumps(
            {
                "predictions": [],
                "resolved": [keep],
                "stats": {"correct": 1, "wrong": 0, "pending": 0, "total": 1, "accuracy": 1.0},
            }
        ),
        encoding="utf-8",
    )
    ticket = mint_ticket("predictions", "merge-stale")
    stale = WriteTicket("predictions", ticket.epoch, ticket.run_id)
    revoke("predictions", reason="stale-merge-test")
    patch = {
        "predictions": [],
        "resolved": [{"id": "row-new", "status": "resolved", "netuid": 9}],
        "stats": {},
    }
    with pytest.raises(TicketRefused):
        ps.save_predictions(patch, ticket=stale, merge_by_id=True)
    on_disk = json.loads(pred_path.read_text(encoding="utf-8"))
    assert any(r.get("id") == "row-keep" for r in on_disk.get("resolved") or [])


@pytest.mark.no_persist_gate
def test_predictions_stale_merge_subprocess_preserves_disk_row(tmp_path, monkeypatch):
    """Cross-process revoke while stale ticket merge must not drop existing resolved rows."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    pred_path = tmp_path / "predictions.json"
    epoch_path = str(tmp_path / "predictions.epoch")
    lock_path = str(tmp_path / "predictions.lock")
    keep_id = "row-subprocess-keep"
    pred_path.write_text(
        json.dumps({"predictions": [], "resolved": [{"id": keep_id, "status": "resolved"}], "stats": {}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PREDICTIONS_EPOCH_PATH", epoch_path)
    monkeypatch.setenv("PREDICTIONS_LOCK_PATH", lock_path)
    env = os.environ.copy()
    env["PYTHONPATH"] = repo_root
    env["PREDICTIONS_PATH"] = str(pred_path)
    env["PREDICTIONS_EPOCH_PATH"] = epoch_path
    env["PREDICTIONS_LOCK_PATH"] = lock_path

    ticket = mint_ticket("predictions", "subprocess-merge")
    stale_epoch = ticket.epoch
    run_id = ticket.run_id
    merge_ok_path = str(tmp_path / "merge_ok.txt")
    commit_script = textwrap.dedent(
        f"""
        from internal.store.domain_write_gate import WriteTicket, revoke
        from internal.learning import predictions_store as ps
        from internal.store.domain_write_gate import TicketRefused
        revoke("predictions", reason="child-before-stale-merge")
        ticket = WriteTicket("predictions", {stale_epoch}, {run_id!r})
        patch = {{"predictions": [], "resolved": [{{"id": "row-would-drop", "status": "resolved"}}], "stats": {{}}}}
        try:
            ps.save_predictions(patch, ticket=ticket, merge_by_id=True)
            ok = False
        except TicketRefused:
            ok = True
        with open({merge_ok_path!r}, "w", encoding="utf-8") as handle:
            handle.write("1" if ok else "0")
        """
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
    assert open(merge_ok_path, encoding="utf-8").read() == "1"
    on_disk = json.loads(pred_path.read_text(encoding="utf-8"))
    assert any(r.get("id") == keep_id for r in on_disk.get("resolved") or [])


@pytest.mark.no_persist_gate
def test_cycle_summary_commit_refused_after_cross_process_revoke(tmp_path, monkeypatch):
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text(json.dumps({"expert_weights": {"quant": 1.0}}), encoding="utf-8")
    epoch_path = str(tmp_path / "cycle_summary.epoch")
    lock_path = str(tmp_path / "soul_map.lock")
    result_path = str(tmp_path / "cycle_result.txt")
    monkeypatch.setenv("CYCLE_SUMMARY_EPOCH_PATH", epoch_path)
    monkeypatch.setenv("SOUL_MAP_LOCK_PATH", lock_path)
    env = os.environ.copy()
    env["PYTHONPATH"] = repo_root

    ticket = mint_ticket("cycle_summary", "cycle-race-parent")
    revoke_script = textwrap.dedent(
        """
        from internal.store.domain_write_gate import revoke
        revoke("cycle_summary", reason="child-race")
        """
    )
    commit_script = textwrap.dedent(
        f"""
        import json
        from internal.store.domain_write_gate import WriteTicket
        from internal.store import soul_map_io
        from internal.store.domain_write_gate import TicketRefused
        soul_path = {str(soul_path)!r}
        ticket = WriteTicket("cycle_summary", {ticket.epoch}, {ticket.run_id!r})
        def mutator(data):
            data["marker"] = "stale-write"
        refused = False
        try:
            soul_map_io.write_soul_map(mutator, soul_path, ticket=ticket)
        except TicketRefused:
            refused = True
        with open({result_path!r}, "w", encoding="utf-8") as handle:
            handle.write("1" if refused else "0")
        """
    )
    for script in (revoke_script, commit_script):
        run_env = env.copy()
        run_env["CYCLE_SUMMARY_EPOCH_PATH"] = epoch_path
        run_env["SOUL_MAP_LOCK_PATH"] = lock_path
        assert (
            subprocess.run(
                [sys.executable, "-c", script],
                env=run_env,
                cwd=repo_root,
                check=False,
            ).returncode
            == 0
        )
    assert open(result_path, encoding="utf-8").read() == "1"
    assert "marker" not in json.loads(soul_path.read_text(encoding="utf-8"))


@pytest.mark.no_persist_gate
def test_daily_pick_downgrade_refused_after_cross_process_revoke(tmp_path, monkeypatch):
    """Ledger-style daily_pick commit with stale epoch must not mutate picks file."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    picks_path = tmp_path / "daily_picks.json"
    picks_path.write_text(
        json.dumps([{"pick_id": "v2:2026-11-05", "date": "2026-11-05", "action": "LONG", "pick": {"netuid": 1}}]),
        encoding="utf-8",
    )
    epoch_path = str(tmp_path / "daily_pick.epoch")
    lock_path = str(tmp_path / "daily_picks.lock")
    result_path = str(tmp_path / "pick_result.txt")
    monkeypatch.setenv("DAILY_PICK_EPOCH_PATH", epoch_path)
    monkeypatch.setenv("DAILY_PICKS_LOCK_PATH", lock_path)
    env = os.environ.copy()
    env["PYTHONPATH"] = repo_root

    ticket = mint_ticket("daily_pick", "pick-race")
    revoke_script = textwrap.dedent(
        """
        from internal.store.domain_write_gate import revoke
        revoke("daily_pick", reason="child-race")
        """
    )
    commit_script = textwrap.dedent(
        f"""
        import json
        import os
        from internal.store.domain_write_gate import WriteTicket, commit
        picks_path = {str(picks_path)!r}
        ticket = WriteTicket("daily_pick", {ticket.epoch}, {ticket.run_id!r})
        def body():
            with open(picks_path, "r", encoding="utf-8") as handle:
                rows = json.load(handle)
            rows[0] = dict(rows[0])
            rows[0]["action"] = "HOLD"
            rows[0]["pick"] = None
            tmp = picks_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(rows, handle)
            os.replace(tmp, picks_path)
        ok = commit(ticket, body)
        with open({result_path!r}, "w", encoding="utf-8") as handle:
            handle.write("1" if ok else "0")
        """
    )
    for script in (revoke_script, commit_script):
        run_env = env.copy()
        run_env["DAILY_PICK_EPOCH_PATH"] = epoch_path
        run_env["DAILY_PICKS_LOCK_PATH"] = lock_path
        assert (
            subprocess.run(
                [sys.executable, "-c", script],
                env=run_env,
                cwd=repo_root,
                check=False,
            ).returncode
            == 0
        )
    assert open(result_path, encoding="utf-8").read() == "0"
    row = json.loads(picks_path.read_text(encoding="utf-8"))[0]
    assert row.get("action") == "LONG"


@pytest.mark.no_persist_gate
def test_load_weights_skips_legacy_repair_without_soul_ticket(tmp_path, monkeypatch):
    from internal.council import weights

    soul = tmp_path / "soul_map.json"
    soul.write_text(
        json.dumps(
            {
                "expert_weights": {"quant": 1.0, "contrarian": 1.5},
                "adversarial_state": {"council_weights": {"quant": 1.0, "contrarian": 1.5}},
            }
        ),
        encoding="utf-8",
    )
    repairs = {"n": 0}

    def _spy(path: str = weights.SOUL_MAP_PATH, predictions_path=None):
        repairs["n"] += 1
        return False

    monkeypatch.setattr(weights, "repair_stale_contrarian_weights", _spy)
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    weights.load_weights(str(soul))
    assert repairs["n"] == 0


def test_corrupt_epoch_refuses_stale_ticket_commit(tmp_path, monkeypatch):
    epoch_path = tmp_path / "predictions.epoch"
    epoch_path.write_text("not-an-int", encoding="utf-8")
    monkeypatch.setenv("PREDICTIONS_EPOCH_PATH", str(epoch_path))
    monkeypatch.setenv("PREDICTIONS_LOCK_PATH", str(tmp_path / "predictions.lock"))
    stale = WriteTicket("predictions", 0, "stale-at-zero")
    assert commit(stale, lambda: None) is False
    revoke("predictions", reason="repair-corrupt")
    assert epoch_path.read_text(encoding="utf-8").strip().isdigit()


def test_append_prediction_mints_web_ticket_when_unbound(tmp_path, monkeypatch):
    from internal.learning import predictions_store as ps

    pred_path = tmp_path / "predictions.json"
    monkeypatch.setattr(ps, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setenv("PREDICTIONS_EPOCH_PATH", str(tmp_path / "predictions.epoch"))
    monkeypatch.setenv("PREDICTIONS_LOCK_PATH", str(tmp_path / "predictions.lock"))
    row = {"id": "pred-1", "netuid": 1, "status": "pending", "horizon_type": "hour"}
    assert ps.append_prediction(row) is True
    on_disk = json.loads(pred_path.read_text(encoding="utf-8"))
    assert any(p.get("id") == "pred-1" for p in on_disk.get("predictions") or [])


def test_merge_predictions_keeps_concurrent_pending_row(tmp_path, monkeypatch):
    from internal.learning import predictions_store as ps

    pred_path = tmp_path / "predictions.json"
    monkeypatch.setattr(ps, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setenv("PREDICTIONS_EPOCH_PATH", str(tmp_path / "predictions.epoch"))
    monkeypatch.setenv("PREDICTIONS_LOCK_PATH", str(tmp_path / "predictions.lock"))
    pred_path.write_text(
        json.dumps(
            {
                "predictions": [{"id": "keep-me", "netuid": 2, "status": "pending"}],
                "resolved": [],
                "stats": {},
            }
        ),
        encoding="utf-8",
    )
    ticket = mint_ticket("predictions", "merge-keep")
    patch = {
        "predictions": [{"id": "patch-row", "netuid": 9, "status": "pending"}],
        "resolved": [],
        "stats": {},
    }
    ps.save_predictions(patch, ticket=ticket, merge_by_id=True)
    on_disk = json.loads(pred_path.read_text(encoding="utf-8"))
    ids = {p.get("id") for p in on_disk.get("predictions") or []}
    assert ids == {"keep-me", "patch-row"}
