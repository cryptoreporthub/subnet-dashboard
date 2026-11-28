"""Production web launch must not trust client-spoofable forwarded headers (#1633)."""

from __future__ import annotations

import os
import runpy
from pathlib import Path
from unittest.mock import patch

from internal.web_uvicorn import UVICORN_FORWARDED_ALLOW_IPS, UVICORN_WEB_KWARGS


def test_uvicorn_forwarded_allow_ips_pinned_loopback():
    assert UVICORN_FORWARDED_ALLOW_IPS == "127.0.0.1"
    assert UVICORN_WEB_KWARGS["forwarded_allow_ips"] == "127.0.0.1"
    assert UVICORN_WEB_KWARGS["proxy_headers"] is False


def test_fly_web_entrypoint_uses_run_web_with_guard():
    entry = Path("scripts/fly_web_entrypoint.sh").read_text()
    assert "run_web_with_guard.py" in entry
    assert "FORWARDED_ALLOW_IPS" not in entry
    assert "uvicorn " not in entry or "run_web_with_guard.py" in entry


def test_fly_worker_entrypoint_uses_pinned_launcher_for_rate_limited_app():
    """Worker HTTP serves server:app (mount_rate_limit at server.py:472) — same kwargs as web."""
    entry = Path("scripts/fly_worker_entrypoint.sh").read_text()
    assert "run_web_with_guard.py" in entry
    assert "UVICORN_TARGET=server:app" in entry
    assert "--proxy-headers" not in entry


def test_procfile_routes_web_through_pinned_launcher():
    proc = Path("Procfile").read_text()
    assert "run_web_with_guard.py" in proc
    assert "uvicorn " not in proc


def test_replit_workflow_uses_pinned_launcher():
    replit = Path(".replit").read_text()
    assert "run_web_with_guard.py" in replit
    assert "uvicorn server:app" not in replit


def test_dockerfile_web_cmd_uses_fly_entrypoint_chain():
    docker = Path("Dockerfile").read_text()
    assert "fly_web_entrypoint.sh" in docker
    assert "CMD" in docker
    assert "uvicorn asgi_entry" not in docker


def test_run_web_with_guard_uvicorn_run_receives_pinned_kwargs():
    """Launcher must pass UVICORN_WEB_KWARGS even when env sets FORWARDED_ALLOW_IPS=* (#1633)."""
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "run_web_with_guard.py"
    captured: dict = {}

    def fake_run(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = dict(kwargs)

    prev_child = os.environ.get("LIVE_SUBNETS_FETCH_CHILD")
    prev_fwd = os.environ.get("FORWARDED_ALLOW_IPS")
    try:
        os.environ["LIVE_SUBNETS_FETCH_CHILD"] = "1"
        os.environ["FORWARDED_ALLOW_IPS"] = "*"
        with patch("uvicorn.run", fake_run):
            runpy.run_path(str(script), run_name="__main__")
    finally:
        if prev_child is None:
            os.environ.pop("LIVE_SUBNETS_FETCH_CHILD", None)
        else:
            os.environ["LIVE_SUBNETS_FETCH_CHILD"] = prev_child
        if prev_fwd is None:
            os.environ.pop("FORWARDED_ALLOW_IPS", None)
        else:
            os.environ["FORWARDED_ALLOW_IPS"] = prev_fwd

    assert "kwargs" in captured
    assert captured["kwargs"]["forwarded_allow_ips"] == "127.0.0.1"
    assert captured["kwargs"]["proxy_headers"] is False