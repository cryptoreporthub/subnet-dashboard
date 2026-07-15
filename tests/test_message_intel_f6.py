"""§17.F6 — message-intel listener hardening."""

from __future__ import annotations

from fastapi.testclient import TestClient

from internal.message_intel import listener_service
from server import app


def test_listener_status_honest_without_creds(monkeypatch):
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER", "auto")
    listener_service._listener = None
    status = listener_service.listener_status()
    assert status["has_creds"] is False
    assert status["live"] is False
    assert status["reason"] == "missing_telegram_creds"


def test_listener_status_disabled(monkeypatch):
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER", "off")
    listener_service._listener = None
    status = listener_service.listener_status()
    assert status["enabled"] is False
    assert status["reason"] == "disabled"
    assert status["live"] is False


def test_start_skipped_without_creds(monkeypatch):
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER", "auto")
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)
    listener_service._listener = None
    assert listener_service.start_message_intel_listeners() is False
    assert listener_service.listener_status()["running"] is False


def test_start_with_mocked_listener(monkeypatch):
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER", "auto")
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "deadbeef")
    listener_service._listener = None

    class _Fake:
        _running = True

        def start(self):
            return True

        def stop(self):
            self._running = False

    monkeypatch.setattr(
        "message_intel.telegram_listener.TelegramListener",
        lambda **kwargs: _Fake(),
    )
    assert listener_service.start_message_intel_listeners() is True
    status = listener_service.listener_status()
    assert status["has_creds"] is True
    assert status["running"] is True
    assert status["live"] is True
    assert status["reason"] == "running"
    listener_service.stop_message_intel_listeners()
    assert listener_service.listener_status()["running"] is False


def test_api_message_intel_status_200():
    client = TestClient(app)
    resp = client.get("/api/message-intel/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert "listener" in body
    assert "reason" in body["listener"]
    assert "empty" in body


def test_api_list_includes_listener_meta(monkeypatch):
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER", "off")
    client = TestClient(app)
    resp = client.get("/api/message-intel")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("empty") is True or isinstance(body.get("messages"), list)
    assert "listener" in (body.get("meta") or {})
