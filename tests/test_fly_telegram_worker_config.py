"""Fly.toml contract for web + dedicated worker (Telegram listener on worker)."""

from __future__ import annotations

from pathlib import Path


def _fly_toml() -> str:
    return Path("fly.toml").read_text(encoding="utf-8")


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


def test_fly_worker_entrypoint_runs_uvicorn_worker_mode():
    script = Path("scripts/fly_worker_entrypoint.sh").read_text(encoding="utf-8")
    assert "RUN_MODE=worker" in script
    assert "uvicorn server:app" in script
    assert "MESSAGE_INTEL_LISTENER" in script
