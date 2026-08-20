"""Fly.toml + fly.yml contract for v1 inline worker on web (prod canon after 2026-08-19 incident)."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


def _fly_toml() -> str:
    return Path("fly.toml").read_text(encoding="utf-8")


def _fly_worker_v2_toml() -> str:
    return Path("fly.worker-v2.toml").read_text(encoding="utf-8")


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


def test_fly_toml_v1_inline_topology():
    """fly.toml is v1 canon: inline worker, volume on web, WORKER_SPLIT_V2=off."""
    fly = _fly_toml()
    assert 'WORKER_SPLIT_V2 = "off"' in fly
    assert 'INLINE_WORKER = "1"' in fly
    assert 'ENABLE_INLINE_WORKER = "1"' in fly
    assert 'processes = ["web"]' in fly
    assert re.search(
        r'\[mounts\][\s\S]*processes = \["web"\]',
        fly,
    )


def test_fly_toml_web_vm_shared_cpu():
    fly = _fly_toml()
    assert re.search(
        r'\[\[vm\]\][\s\S]*size = "shared-cpu-2x"[\s\S]*memory = "2gb"[\s\S]*processes = \["web"\]',
        fly,
    )


# --- fly.worker-v2.toml (v2 kit — not deployed until Stage 3) ---


def test_fly_worker_v2_toml_topology():
    """fly.worker-v2.toml is the v2 kit: dedicated worker, volume on worker."""
    fly = _fly_worker_v2_toml()
    assert 'INLINE_WORKER = "0"' in fly
    assert 'ENABLE_INLINE_WORKER = "0"' in fly
    assert 'processes = ["worker"]' in fly
    assert 'processes = ["web"]' in fly
    assert "WORKER_HTTP_PORT" in fly
    assert "internal_port = 8081" in fly


def test_fly_worker_v2_toml_does_not_preset_split_v2():
    """fly.worker-v2.toml must NOT set WORKER_SPLIT_V2=on in [env].

    The enable script sets it as a Fly secret AFTER the worker is proven
    healthy. If the toml pre-sets it, deploy flips split_v2 on before
    health is verified — the exact bug class from the 01:59 incident.
    """
    fly = _fly_worker_v2_toml()
    assert 'WORKER_SPLIT_V2 = "on"' not in fly


def test_fly_worker_v2_toml_sh_prefix():
    """Both entrypoints in fly.worker-v2.toml must use sh prefix."""
    fly = _fly_worker_v2_toml()
    assert 'web = "sh ./scripts/fly_web_entrypoint.sh"' in fly
    assert 'worker = "sh ./scripts/fly_worker_entrypoint.sh"' in fly


def test_fly_worker_v2_toml_worker_vm():
    fly = _fly_worker_v2_toml()
    assert re.search(
        r'\[\[vm\]\]\s+size\s*=\s*"shared-cpu-1x"\s+memory\s*=\s*"2gb"\s+processes\s*=\s*\["worker"\]',
        fly,
    )


# --- Entrypoint scripts ---


def test_fly_worker_entrypoint_runs_uvicorn_worker_mode():
    script = Path("scripts/fly_worker_entrypoint.sh").read_text(encoding="utf-8")
    assert "RUN_MODE=worker" in script
    assert "uvicorn server:app" in script
    assert "MESSAGE_INTEL_LISTENER" in script


# --- fly.yml (v1 inline deploy — from PR #999) ---


def test_fly_yml_scales_v1_inline():
    yml = _fly_yml()
    assert "flyctl scale count web=1" in yml
    assert "worker=0" in yml
    assert "flyctl scale count web=1 worker=1" not in yml


def test_fly_yml_verifies_v1_topology():
    yml = _fly_yml()
    assert "Verify Fly process topology (web=1, no dedicated worker)" in yml
    assert "counts['worker'] > 0" in yml


def test_fly_yml_verifies_inline_readiness():
    yml = _fly_yml()
    assert "Verify v1 inline readiness" in yml
    assert "split_v2" in yml


def test_fly_yml_clears_v2_secrets_before_deploy():
    yml = _fly_yml()
    assert "secrets unset WORKER_SPLIT_V2" in yml
    assert "Prep split v2 deploy" not in yml
    assert "fly_wait_worker_peer_alive.sh" not in yml


# --- Enable / soak / cutover scripts ---


def test_fly_enable_v2_secret_after_health():
    """fly_enable_worker_v2.sh must set WORKER_SPLIT_V2=on AFTER worker is healthy."""
    script = Path("scripts/fly_enable_worker_v2.sh").read_text(encoding="utf-8")
    deploy_pos = script.find("flyctl deploy")
    secret_pos = script.find("flyctl secrets set WORKER_SPLIT_V2=on")
    assert deploy_pos > 0, "enable script must deploy"
    assert secret_pos > 0, "enable script must set WORKER_SPLIT_V2=on"
    assert secret_pos > deploy_pos, "secret must come AFTER deploy"
    probe_pos = script.find("fly_probe_worker_from_web")
    assert probe_pos > 0, "enable script must probe worker from web"
    assert secret_pos > probe_pos, "secret must come AFTER probe gate"


def test_fly_soak_probe_script_exists():
    """Stage 2 soak probe script must exist and have zero-failure gate."""
    script = Path("scripts/fly_soak_probe_worker.sh").read_text(encoding="utf-8")
    assert "SOAK_HOURS" in script
    assert "PROBE_INTERVAL_SECONDS" in script
    assert "zero" in script.lower() or "ZERO" in script
    assert "SOAK FAILED" in script
    assert "SOAK PASSED" in script
    assert "fly_probe_worker_from_web.sh" in script
    assert "MAX_GAP_SECONDS" in script or "CADENCE GAP" in script
    assert "lease currently held" in script


def test_fly_stage2_soak_gha_workflow():
    """Stage 2 soak must run on GHA workflow_dispatch with 4h timeout."""
    yml = Path(".github/workflows/fly-stage2-soak.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in yml
    assert "timeout-minutes: 259" in yml
    assert "243.7" in yml or "32306510707" in yml
    assert "fly_soak_probe_worker.sh" in yml
    assert "confirm == 'soak'" in yml


def test_fly_stage2_temp_worker_script():
    """Stage 2 temp worker deploys via v2 kit services, not machine run."""
    script = Path("scripts/fly_stage2_temp_worker.sh").read_text(encoding="utf-8")
    assert "flyctl machine run" not in script
    assert "fly.worker-v2-hop.toml" in script
    assert "--process-groups worker" in script
    hop = Path("fly.worker-v2-hop.toml").read_text(encoding="utf-8")
    assert "[[services]]" in hop
    assert "internal_port = 8081" in hop
    assert 'STAGE2_HOP = "1"' in hop
    assert re.search(r"^\[mounts\]", hop, re.MULTILINE) is None
    # Networking block must match fly.worker-v2.toml (background env may differ).
    v2 = Path("fly.worker-v2.toml").read_text(encoding="utf-8")
    svc = '[[services]]\n  protocol = "tcp"\n  internal_port = 8081'
    assert hop.count(svc) == 1 and v2.count(svc) == 1
    for key in (
        'auto_stop_machines = "off"',
        "auto_start_machines = true",
        "min_machines_running = 1",
        "port = 8081",
        'handlers = ["http"]',
        'interval = "30s"',
        'timeout = "5s"',
        'grace_period = "30s"',
        'path = "/health"',
    ):
        assert key in hop and key in v2


def test_fly_stage2_representative_soak_toml():
    """Stage 2b representative config: volume + essential, no STAGE2_HOP."""
    soak = Path("fly.worker-v2-essential-soak.toml").read_text(encoding="utf-8")
    hop = Path("fly.worker-v2-hop.toml").read_text(encoding="utf-8")
    assert 'STAGE2_REPRESENTATIVE = "1"' in soak
    assert 'STAGE2_HOP = "1"' not in soak
    assert 'WORKER_HEAVY = "essential"' in soak
    assert 'WORKER_HEAVY = "off"' not in soak
    assert 'MESSAGE_INTEL_LISTENER = "auto"' in soak
    assert re.search(r'\[mounts\][\s\S]*processes = \["worker"\]', soak)
    assert 'STAGE2_HOP = "1"' in hop


def test_fly_stage2_representative_scripts_exist():
    for name in (
        "fly_stage2_representative_worker.sh",
        "fly_stage2_representative_rollback.sh",
        "fly_v1_freshness_gate.sh",
        "fly_tmp_boot_reaper.sh",
        "fly_stage2_soak_sample.sh",
        "tmp_boot_reap_once.py",
    ):
        path = Path("scripts") / name
        assert path.is_file(), f"missing {path}"
    worker = Path("scripts/fly_stage2_representative_worker.sh").read_text(encoding="utf-8")
    assert "fly_v1_freshness_gate.sh" in worker
    assert "fly.worker-v2-essential-soak.toml" in worker
    assert "flyctl secrets set WORKER_SPLIT_V2=on" not in worker
    rollback = Path("scripts/fly_stage2_representative_rollback.sh").read_text(encoding="utf-8")
    assert "fly.toml" in rollback


def test_fly_stage2_representative_soak_gha_workflow():
    yml = Path(".github/workflows/fly-stage2-representative-soak.yml").read_text(encoding="utf-8")
    assert "soak-representative" in yml
    assert "fly_soak_probe_worker.sh" in yml
    assert "fly_v1_freshness_gate.sh" in yml
    assert "validate_stage2_soak_log.py" in yml
    assert "SOAK_INSTRUMENT" in yml or "soak_samples" in yml


def test_fly_v1_freshness_gate_strict():
    script = Path("scripts/fly_v1_freshness_gate.sh").read_text(encoding="utf-8")
    assert "learning-health is" in script or "status not in" in script
    assert "degraded" in script
    assert "daily pick scheduler timeout" in script or "timed out" in script
    assert "subnet_sync_last_ok=0" in script
    assert "MAX_LEARNING_HEALTH_LATENCY_SECONDS" in script


def test_fly_soak_probe_instruments_when_enabled():
    script = Path("scripts/fly_soak_probe_worker.sh").read_text(encoding="utf-8")
    assert "fly_stage2_soak_sample.sh" in script
    assert "SOAK_INSTRUMENT" in script


def test_stage2_hop_skips_telegram_despite_secrets(monkeypatch):
    from internal.message_intel import summary_bot
    from internal.run_mode import stage2_hop_mode

    monkeypatch.setenv("STAGE2_HOP", "1")
    monkeypatch.setenv("TELEGRAM_SUMMARY_BOT", "on")
    assert stage2_hop_mode() is True
    assert summary_bot.summary_bot_enabled() is False


def test_fly_probe_requires_flycast_ok():
    """Hop proof must require flycast path OK (not just any candidate)."""
    script = Path("scripts/fly_probe_worker_from_web.sh").read_text(encoding="utf-8")
    assert ".flycast:" in script
    assert "/health" in script
    assert "/api/ops/worker-peer" in script
    assert "worker_peer.alive is not true" in script


def test_probe_worker_peer_once_requires_alive_true():
    script = Path("scripts/probe_worker_peer_once.py").read_text(encoding="utf-8")
    assert "worker_peer.alive" in script
    assert "alive is not True" in script or "alive={alive" in script


def test_fly_v2_cutover_gate_script_exists():
    """Stage 3 cutover gate script must check all required conditions."""
    script = Path("scripts/fly_v2_cutover_gate.sh").read_text(encoding="utf-8")
    assert "worker_mode" in script
    assert "worker_peer" in script
    assert "data-freshness" in script
    assert "skipping inline worker" in script
    assert "GATE FAIL" in script
    assert "ROLLBACK" in script or "rollback" in script


def _run_web_entrypoint_skip_only(env: dict[str, str]) -> str:
    """Run only _start_inline_worker from fly_web_entrypoint.sh (no supervise/uvicorn)."""
    src = Path("scripts/fly_web_entrypoint.sh").read_text(encoding="utf-8")
    # Drop supervise (infinite loop when ENABLE=1) and uvicorn exec.
    marker = "_start_inline_worker\n_supervise_inline_worker\nexec python scripts/run_web_with_guard.py"
    assert marker in src, "entrypoint tail changed — update this test"
    stub = src.replace(
        marker,
        '_start_inline_worker\necho "entrypoint stub exit"\nexit 0\n',
    )
    merged = dict(os.environ)
    merged["ENABLE_INLINE_WORKER"] = "1"
    merged["WORKER_SPLIT_V2"] = "off"
    merged.update(env)
    proc = subprocess.run(
        ["sh", "-s"],
        input=stub,
        capture_output=True,
        text=True,
        timeout=10,
        env=merged,
        check=False,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    return proc.stdout


def test_web_entrypoint_logs_skip_under_v2_enable_inline_off():
    """Stage 3 fly.worker-v2.toml sets ENABLE_INLINE_WORKER=0; gate needs this log."""
    out = _run_web_entrypoint_skip_only(
        {"ENABLE_INLINE_WORKER": "0", "WORKER_SPLIT_V2": "off"}
    )
    assert "skipping inline worker" in out.lower()
    assert "starting inline" not in out.lower()


def test_web_entrypoint_logs_skip_when_split_v2_on():
    out = _run_web_entrypoint_skip_only(
        {"ENABLE_INLINE_WORKER": "1", "WORKER_SPLIT_V2": "on"}
    )
    assert "skipping inline worker" in out.lower()
    assert "starting inline" not in out.lower()


# --- Utility scripts ---


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
    for line in diag.splitlines():
        if "jq -r" in line:
            assert '\\"' not in line, f"jq line must not use backslash-escaped quotes: {line}"


def test_worker_diag_jq_machine_selectors():
    """Mirror scripts/worker-diag.sh jq — must compile and pick worker when split v2."""
    import json
    import subprocess

    machines = [
        {"id": "w1", "state": "started", "process_group": "web"},
        {"id": "k1", "state": "running", "config": {"process_group": "worker"}},
    ]
    payload = json.dumps(machines)
    worker_q = (
        '[.[] | select(((.process_group // .config.process_group // "") | ascii_downcase) == "worker" '
        'and (.state == "running" or .state == "started"))][0].id // empty'
    )
    web_q = (
        '[.[] | select(((.process_group // .config.process_group // "web") == "web" '
        'and .state == "running"))][0].id // empty'
    )
    list_q = r'.[] | "\(.id) state=\(.state) pg=\(.process_group // .config.process_group // "web")"'

    worker = subprocess.run(
        ["jq", "-r", worker_q], input=payload, text=True, capture_output=True, check=True
    )
    assert worker.stdout.strip() == "k1"

    web_only = json.dumps([{"id": "w1", "state": "running", "process_group": "web"}])
    web = subprocess.run(
        ["jq", "-r", web_q], input=web_only, text=True, capture_output=True, check=True
    )
    assert web.stdout.strip() == "w1"

    listed = subprocess.run(
        ["jq", "-r", list_q], input=payload, text=True, capture_output=True, check=True
    )
    assert "k1 state=running pg=worker" in listed.stdout


def test_machine_process_group_counts_v1():
    """Mirror fly.yml post-deploy v1 topology guard."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "fly_v2_volume_repair",
        Path(__file__).with_name("test_fly_v2_volume_repair.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    machine_process_group = mod.machine_process_group

    machines = [
        {"id": "w1", "config": {"metadata": {"fly_process_group": "web"}}, "state": "started"},
    ]
    counts = {"web": 0, "worker": 0}
    for m in machines:
        pg = machine_process_group(m)
        if pg in counts:
            counts[pg] += 1
    assert counts == {"web": 1, "worker": 0}
