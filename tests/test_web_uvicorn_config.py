"""Production web launch must not trust client-spoofable forwarded headers (#1633)."""

from __future__ import annotations

from pathlib import Path

from internal.web_uvicorn import UVICORN_FORWARDED_ALLOW_IPS, UVICORN_WEB_KWARGS


def test_uvicorn_forwarded_allow_ips_pinned_loopback():
    assert UVICORN_FORWARDED_ALLOW_IPS == "127.0.0.1"
    assert UVICORN_WEB_KWARGS["forwarded_allow_ips"] == "127.0.0.1"
    assert UVICORN_WEB_KWARGS["proxy_headers"] is True


def test_fly_web_entrypoint_uses_run_web_with_guard():
    entry = Path("scripts/fly_web_entrypoint.sh").read_text()
    assert "run_web_with_guard.py" in entry
    assert "FORWARDED_ALLOW_IPS" not in entry


def test_run_web_with_guard_passes_pinned_forwarded_allow_ips():
    source = Path("scripts/run_web_with_guard.py").read_text()
    assert "UVICORN_WEB_KWARGS" in source
    assert 'os.environ.pop("FORWARDED_ALLOW_IPS", None)' in source