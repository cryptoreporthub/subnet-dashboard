Title: 

URL Source: https://raw.githubusercontent.com/cryptoreporthub/subnet-dashboard/main/tests/test_fly_telegram_worker_config.py

Markdown Content:
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


def test_fly_toml_does_not_declare_worker_process_group():
    """v1 fly.toml must not list a worker process — flyctl deploy would spawn one."""
    fly = _fly_toml()
    match = re.search(r"\[processes\](.*?)(?=\n\[|\Z)", fly, re.S)
    assert match, "fly.toml missing [processes]"
    block = match.group(1)
    assert not re.search(r"^\s*worker\s*=", block, re.M)
    assert 'web = "sh ./scripts/fly_web_entrypoint.sh"' in block


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


def test_fly_toml_web_vm_performance_4gb():
    """Web VM pinned to performance-1x 4GB after dpick memory cliff (#1024)."""
    fly = _fly_toml()
    assert re.search(
        r'\[\[vm\]\][\s\S]*size = "performance-1x"[\s\S]*memory = "4gb"[\s\S]*processes = \["web"\]',
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


def test_dockerfile_bakes_sentry_release_from_git_sha():
    docker = Path("Dockerfile").read_text(encoding="utf-8")
    assert "ARG GIT_SHA" in docker
    assert "ENV SENTRY_RELEASE=${GIT_SHA}" in docker


def test_fly_yml_dispatch_or_fly_deploy_label_not_push():
    """Deploy is workflow_dispatch or owner `fly-deploy` label; push-to-main stays off.

    #1185: the deploy checkout ref resolves at runtime via the deploy_ref step
    (steps.deploy_ref.outputs.ref). Merged docs-only vehicles under
    docs/deploy-vehicles/* retarget refs/heads/main so /version gates on the main
    short SHA; unmerged labeled PRs deploy the PR head SHA. The pre-#1185 inline
    `github.event.pull_request.head.sha || github.sha` expression must be gone.
    """
    yml = _fly_yml()
    on_block = yml.split("jobs:", 1)[0]
    assert "workflow_dispatch:" in on_block
    assert "pull_request:" in on_block
    assert "types: [labeled]" in on_block
    assert "\n  push:" not in on_block
    gate = (
        "github.event_name == 'workflow_dispatch' || "
        "(github.event_name == 'pull_request' && "
        "github.event.label.name == 'fly-deploy' && "
        "github.event.pull_request.head.repo.full_name == github.repository && "
        "github.actor == 'cryptoreporthub')"
    )
    assert yml.count(gate) == 2
    # #1185: ref-resolve step replaced the inline head.sha || github.sha expression.
    assert "steps.deploy_ref.outputs.ref" in yml
    assert yml.count("ref: ${{ steps.deploy_ref.outputs.ref }}") == 2
    # Merged docs-only vehicles retarget origin/main; non-docs merged PRs fail closed.
    assert "refs/heads/main" in yml
    assert "docs/deploy-vehicles/*" in yml
    # Migration guard: the pre-#1185 inline ref expression is gone.
    assert "github.event.pull_request.head.sha || github.sha" not in yml


def test_fly_yml_passes_sentry_release_build_arg():
    yml = _fly_yml()
    assert "git rev-parse HEAD" in yml
    assert "--build-arg" in yml and "GIT_SHA=" in yml


def test_fly_yml_verifies_sentry_release_on_machine():
    yml = _fly_yml()
    assert "Verify SENTRY_RELEASE on deployed machine" in yml
    assert "printenv SENTRY_RELEASE" in yml
    assert "does not match deploy SHA" in yml


def test_fly_yml_scales_v1_inline():
    yml = _fly_yml()
    assert "flyctl scale count web=1" in yml
    assert "worker=0" in yml
    assert "flyctl scale count web=1 worker=1" not in yml
    deploy_pos = yml.find("flyctl deploy --config fly.toml")
    scale_pos = yml.find("Scale web=1 worker=0 (v1 inline, required)")
    verify_pos = yml.find("Verify Fly process topology (web=1, no dedicated worker)")
    assert deploy_pos > 0 and scale_pos > deploy_pos, "worker=0 scale must run after deploy"
    assert verify_pos > scale_pos, "topology verify must run after worker=0 scale"


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
    from internal.run_mode import stage

[read_links truncated 7218 chars from this runtime tool output. The full content is stored with the tool result.]