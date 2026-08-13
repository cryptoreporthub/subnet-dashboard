"""Fly.toml contract for web + dedicated worker (Telegram listener on worker)."""

from __future__ import annotations

import re
from pathlib import Path


def _fly_toml() -> str:
    return Path("fly.toml").read_text(encoding="utf-8")


def _fly_yml() -> str:
    return Path(".github/workflows/fly.yml").read_text(encoding="utf-8")


def test_fly_toml_preserves_web_process():
    fly = _fly_toml()
    assert 'web = "sh ./scripts/fly_web_entrypoint.sh"' in fly


def test_fly_toml_worker_uses_repo_entrypoint():
    fly = _fly_toml()
    assert 'worker = "./scripts/fly_worker_entrypoint.sh"' in fly


def test_fly_toml_message_intel_listener_auto():
    fly = _fly_toml()
    assert 'MESSAGE_INTEL_LISTENER = "auto"' in fly
    assert 'MESSAGE_INTEL_LISTENER = "off"' not in fly


def test_fly_toml_split_v2_worker_topology():
    fly = _fly_toml()
    assert 'WORKER_SPLIT_V2 = "on"' in fly
    assert 'INLINE_WORKER = "0"' in fly
    assert 'ENABLE_INLINE_WORKER = "0"' in fly
    assert 'processes = ["worker"]' in fly
    assert 'processes = ["web"]' in fly
    assert "WORKER_HTTP_PORT" in fly
    assert "internal_port = 8081" in fly


def test_fly_toml_worker_uses_dedicated_cpu_and_preserves_memory():
    fly = _fly_toml()
    assert re.search(
        r'\[\[vm\]\]\s+size = "performance-1x"\s+memory = "2gb"\s+processes = \["worker"\]',
        fly,
    )


def test_fly_worker_entrypoint_runs_uvicorn_worker_mode():
    script = Path("scripts/fly_worker_entrypoint.sh").read_text(encoding="utf-8")
    assert "RUN_MODE=worker" in script
    assert "uvicorn server:app" in script
    assert "MESSAGE_INTEL_LISTENER" in script


def test_fly_yml_scales_web_and_worker():
    yml = _fly_yml()
    assert "flyctl scale count web=1 worker=1" in yml
    assert "worker=0" not in yml
    assert "Rollback split_v2" not in yml


def test_fly_yml_verifies_process_topology():
    yml = _fly_yml()
    assert "Verify Fly process topology" in yml
    assert "counts['web'] < 1 or counts['worker'] < 1" in yml


def test_fly_yml_waits_for_worker_peer_alive():
    yml = _fly_yml()
    assert "Wait for worker peer" in yml
    assert "fly_wait_worker_peer_alive.sh" in yml


def test_fly_yml_prep_split_v2_before_deploy():
    yml = _fly_yml()
    assert "Prep split v2 deploy" in yml
    assert "fly_split_v2_deploy_prep.sh" in yml
    assert "prep_retry" in yml


def test_fly_split_v2_deploy_prep_script():
    script = Path("scripts/fly_split_v2_deploy_prep.sh").read_text(encoding="utf-8")
    assert "fly_v2_volume_repair.sh" in script
    assert "has_volume_mount" in script or "volume mount" in script
    assert "created" in script and "starting" in script


def test_fly_wait_worker_peer_alive_script():
    script = Path("scripts/fly_wait_worker_peer_alive.sh").read_text(encoding="utf-8")
    assert "fly_probe_worker_from_web.sh" in script
    assert "/api/ops/readiness" in script
    assert "worker_peer.alive" in script or "worker_peer" in script
    assert "GUARD FAIL" in script


def test_fly_probe_worker_from_web_fails_without_web():
    script = Path("scripts/fly_probe_worker_from_web.sh").read_text(encoding="utf-8")
    assert "no web machine" in script
    assert "exit 1" in script


def test_fly_worker_split_v2_guard_reads_fly_toml():
    guard = Path("scripts/fly_worker_split_v2_guard.sh").read_text(encoding="utf-8")
    assert "fly.toml" in guard
    assert "WORKER_SPLIT_V2" in guard


def test_diag_scripts_use_grep_not_rg():
    """Portable diagnostics — GitHub runners may not have ripgrep."""
    workflow_paths = [
        Path(".github/workflows/fly-worker-diag.yml"),
        Path(".github/workflows/worker-diag-v1.yml"),
    ]
    for path in workflow_paths:
        text = path.read_text(encoding="utf-8")
        assert "grep" in text
        assert not re.search(r"\brg\b", text), f"{path} must not use rg"
    diag = Path("scripts/worker-diag.sh").read_text(encoding="utf-8")
    assert not re.search(r"\brg\b", diag), "worker-diag.sh must not use rg"


def test_machine_process_group_counts():
    """Mirror fly.yml post-deploy topology guard."""
    from tests.test_fly_v2_volume_repair import machine_process_group

    machines = [
        {"id": "w1", "config": {"metadata": {"fly_process_group": "web"}}, "state": "started"},
        {"id": "k1", "config": {"metadata": {"fly_process_group": "worker"}}, "state": "started"},
    ]
    counts = {"web": 0, "worker": 0}
    for m in machines:
        pg = machine_process_group(m)
        if pg in counts:
            counts[pg] += 1
    assert counts == {"web": 1, "worker": 1}
