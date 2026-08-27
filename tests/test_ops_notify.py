"""Logging-only notify audit surface (Policy §4 redaction)."""

from __future__ import annotations

from internal.ops.notify import notify, recent_records, redact, reset_records


def setup_function() -> None:
    reset_records()


def test_redact_strips_bearer_and_sensitive_keys():
    payload = redact(
        {
            "Authorization": "Bearer abc.def",
            "nested": {"token": "sekrit", "path": "/api/registry"},
            "note": "Authorization: Bearer abc.def",
            "access_token": "SECRET",
            "basic_note": "Authorization: Basic SECRET",
        }
    )
    assert payload["Authorization"] == "[redacted]"
    assert payload["nested"]["token"] == "[redacted]"
    assert payload["nested"]["path"] == "/api/registry"
    assert payload["access_token"] == "[redacted]"
    assert "[redacted]" in payload["note"]
    assert "abc.def" not in payload["note"]
    assert "SECRET" not in payload["basic_note"]
    assert "distinct_presented_secrets" not in str(payload)


def test_notify_returns_audit_id_and_stores_redacted_record():
    audit_id = notify(
        "detection",
        bot="shield",
        run_id="run1",
        payload={"authorization": "Bearer leaked", "risk": "high"},
    )
    assert audit_id
    records = recent_records()
    assert records[-1]["audit_id"] == audit_id
    assert records[-1]["event"] == "detection"
    assert records[-1]["payload"]["authorization"] == "[redacted]"
    assert records[-1]["payload"]["risk"] == "high"
    assert "leaked" not in str(records[-1])
