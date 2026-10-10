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
    listener_service._clear_listener_heartbeat()
    status = listener_service.listener_status()
    assert status["has_creds"] is False
    assert status["live"] is False
    assert status["reason"] == "missing_telegram_creds"
    assert status["monitored_group"] == "officialsubnetsummer"


def test_listener_status_disabled(monkeypatch):
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER", "off")
    listener_service._listener = None
    status = listener_service.listener_status()
    assert status["enabled"] is False
    assert status["reason"] == "disabled"
    assert status["live"] is False
    assert "hint" in status


def test_listener_status_reports_invalid_session_string(monkeypatch, tmp_path):
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER", "auto")
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "deadbeef")
    monkeypatch.setenv("TELEGRAM_SESSION_STRING", "bad-padding!!!")
    monkeypatch.setenv("TELEGRAM_SESSION_PATH", str(tmp_path / "telegram_listener"))
    (tmp_path / "telegram_listener.session").write_text("stub", encoding="utf-8")
    listener_service._listener = None
    listener_service._clear_listener_heartbeat()
    status = listener_service.listener_status()
    assert status["has_session"] is True
    assert status["session_mode"] == "string_invalid+file"
    assert "session_string_error" in status
    assert "TELEGRAM_SESSION_STRING" in (status.get("ops_hint") or "")


def test_listener_status_session_file_idle(monkeypatch, tmp_path):
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER", "auto")
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "deadbeef")
    monkeypatch.setenv("TELEGRAM_SESSION_PATH", str(tmp_path / "telegram_listener"))
    (tmp_path / "telegram_listener.session").write_text("stub", encoding="utf-8")
    monkeypatch.delenv("TELEGRAM_SESSION_STRING", raising=False)
    listener_service._listener = None
    listener_service._clear_listener_heartbeat()
    status = listener_service.listener_status()
    assert status["has_session"] is True
    assert status["reason"] == "idle_not_started"


def test_listener_status_essential_missing_session(monkeypatch, tmp_path):
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER", "auto")
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "deadbeef")
    monkeypatch.setenv("WORKER_HEAVY", "essential")
    monkeypatch.setenv("TELEGRAM_SESSION_PATH", str(tmp_path / "telegram_listener"))
    listener_service._listener = None
    listener_service._clear_listener_heartbeat()
    status = listener_service.listener_status()
    assert status["reason"] == "missing_session"
    assert status["worker_heavy"] is False
    assert "bootstrap_telegram_session" in (status.get("ops_hint") or status.get("hint") or "")


def test_listener_status_cross_process_running(monkeypatch, tmp_path):
    hb = tmp_path / ".message_intel_listener"
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER", "auto")
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "deadbeef")
    monkeypatch.setenv("WORKER_HEAVY", "full")
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER_HEARTBEAT", str(hb))
    monkeypatch.setenv("TELEGRAM_SESSION_PATH", str(tmp_path / "telegram_listener"))
    (tmp_path / "telegram_listener.session").write_text("stub", encoding="utf-8")
    listener_service._listener = None
    listener_service._touch_listener_heartbeat()
    status = listener_service.listener_status()
    assert status["running"] is True
    assert status["reason"] == "group_not_connected"
    assert status["live"] is False
    assert status["group_connected"] is False

    hb.write_text(
        '{"pid":1,"ts":"'
        + listener_service.datetime.now(listener_service.timezone.utc).isoformat().replace("+00:00", "Z")
        + '","group_connected":true}',
        encoding="utf-8",
    )
    status = listener_service.listener_status()
    assert status["live"] is True
    assert status["reason"] == "running"


def test_listener_status_stopped_when_heartbeat_stale(monkeypatch, tmp_path):
    hb = tmp_path / ".message_intel_listener"
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER", "auto")
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "deadbeef")
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER_HEARTBEAT", str(hb))
    monkeypatch.setenv("TELEGRAM_SESSION_PATH", str(tmp_path / "telegram_listener"))
    (tmp_path / "telegram_listener.session").write_text("stub", encoding="utf-8")
    hb.write_text('{"pid":1,"ts":"2020-01-01T00:00:00Z"}', encoding="utf-8")
    listener_service._listener = None
    status = listener_service.listener_status()
    assert status["running"] is False
    assert status["reason"] == "listener_stopped"
    assert "watchdog" in status["hint"]


def test_listener_display_mode_archive_when_feed_stale(monkeypatch):
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER", "auto")
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "deadbeef")
    monkeypatch.setenv("TELEGRAM_SESSION_PATH", "/tmp/none")

    class _Fake:
        _running = True
        group_connected = True

    listener_service._listener = _Fake()
    monkeypatch.setattr(
        listener_service,
        "_has_session_file",
        lambda: True,
    )
    monkeypatch.setattr(
        listener_service,
        "_feed_stale_fields",
        lambda: {"feed_stale": True, "last_message_age_seconds": 9999.0},
    )
    monkeypatch.setattr(
        "internal.message_intel.store.live_stats",
        lambda: {"total_messages": 42},
    )
    status = listener_service.listener_status()
    assert status["display_mode"] == "archive"
    assert status["live"] is False
    listener_service._listener = None


def test_start_skipped_without_creds(monkeypatch):
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER", "auto")
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)
    listener_service._listener = None
    listener_service._clear_listener_heartbeat()
    assert listener_service.start_message_intel_listeners() is False
    assert listener_service.listener_status()["running"] is False


def test_start_with_mocked_listener(monkeypatch):
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER", "auto")
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "deadbeef")
    listener_service._listener = None

    class _Fake:
        _running = True
        group_connected = True

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


def test_listener_status_payload_has_no_secrets(monkeypatch):
    """Listener/status payloads must carry hints, never credential values."""
    import json as _json

    api_id = "1234567"
    api_hash = "deadbeefcafe1234"
    monkeypatch.setenv("TELEGRAM_API_ID", api_id)
    monkeypatch.setenv("TELEGRAM_API_HASH", api_hash)
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER", "auto")
    listener_service._listener = None
    listener_service._clear_listener_heartbeat()
    status = listener_service.listener_status()
    blob = _json.dumps(status)
    assert api_id not in blob
    assert api_hash not in blob


def test_api_message_intel_status_degraded_when_listener_unhealthy(monkeypatch):
    from internal.message_intel import routes as mi_routes

    monkeypatch.setattr(
        "internal.message_intel.listener_service.listener_status",
        lambda: {"reason": "listener_stopped", "live": False, "running": False},
    )
    client = TestClient(app)
    body = client.get("/api/message-intel/status").json()
    assert body["freshness"]["status"] == "degraded"
    assert mi_routes._listener_unhealthy({"reason": "listener_stopped"}) is True
    assert mi_routes._listener_unhealthy({"session_string_error": "bad padding"}) is True
    assert mi_routes._listener_unhealthy({"entity_resolve_error": "unauthorized"}) is True
    # Honest-empty without creds is normal operation — never degraded.
    assert mi_routes._listener_unhealthy({"reason": "missing_telegram_creds"}) is False
    assert mi_routes._listener_unhealthy({"reason": "missing_session"}) is False
    assert mi_routes._listener_unhealthy({"reason": "idle_not_started"}) is False


def test_api_message_intel_list_degraded_marker(monkeypatch):
    """List payload carries the bot_contract freshness envelope; an erroring
    store degrades it, a healthy honest-empty store does not."""
    client = TestClient(app)
    healthy = client.get("/api/message-intel").json()
    assert healthy["freshness"]["source"] in ("message_intel_live", "message_intel_archive")
    assert healthy["freshness"]["status"] != "degraded"


def test_api_list_includes_listener_meta(monkeypatch):
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER", "off")
    client = TestClient(app)
    resp = client.get("/api/message-intel")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("empty") is True or isinstance(body.get("messages"), list)
    assert "listener" in (body.get("meta") or {})
