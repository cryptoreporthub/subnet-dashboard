"""Phase D security housekeeping tests."""

from fastapi.testclient import TestClient

import server


def test_csp_enforced_when_flag_on(monkeypatch):
    monkeypatch.setenv("CONTENT_SECURITY_POLICY_ENFORCE", "1")
    monkeypatch.delenv("CONTENT_SECURITY_POLICY", raising=False)
    monkeypatch.delenv("CONTENT_SECURITY_POLICY_REPORT_ONLY", raising=False)
    from internal.security_headers import security_header_items

    names = dict(security_header_items())
    assert "Content-Security-Policy" in names
    assert "Content-Security-Policy-Report-Only" not in names


def test_learning_trigger_error_sanitized(monkeypatch):
    monkeypatch.setenv("DISABLE_BACKGROUND_SCANS", "1")
    client = TestClient(server.app)
    resp = client.post("/api/learning/trigger")
    assert resp.status_code in (200, 503)
    body = resp.text
    assert "Traceback" not in body


def test_pump_scan_error_sanitized(monkeypatch):
    monkeypatch.setenv("DISABLE_BACKGROUND_SCANS", "1")

    def _boom():
        raise RuntimeError("secret_internal_path=/etc/shadow")

    monkeypatch.setattr("internal.pump.routes.scan_all_subnets", _boom)
    client = TestClient(server.app)
    resp = client.post("/api/pump-ladder/scan")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("error") == "pump_scan_failed"
    assert "shadow" not in str(data)
