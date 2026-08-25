"""Sentry init, scrubbing, and TaoStats noise filter."""

import logging

from internal.sentry_setup import (
    before_send,
    init_sentry,
    _is_known_taostats_pool_latest_404,
    _scrub_event,
)


def test_init_sentry_noop_without_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert init_sentry() is False


def test_init_sentry_active_with_dsn(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://examplePublicKey@o0.ingest.sentry.io/0")
    monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    assert init_sentry() is True


def test_init_sentry_reads_release(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://examplePublicKey@o0.ingest.sentry.io/0")
    monkeypatch.setenv("SENTRY_RELEASE", "abc123def")
    init_sentry()
    import sentry_sdk

    options = sentry_sdk.get_client().options
    assert options["release"] == "abc123def"
    assert options["send_default_pii"] is False


def _taostats_event(path: str, status: int, body: str = "snippet") -> dict:
    return {
        "logger": "fetchers.taostats_client",
        "logentry": {
            "message": "TaoStats %s returned %d body=%s",
            "params": (path, status, body),
        },
    }


def test_drop_taostats_pool_latest_404():
    event = _taostats_event("/dtao/pool/latest/v1", 404)
    assert before_send(event, {}) is None


def test_drop_taostats_pool_latest_404_uvicorn_logger():
    event = _taostats_event("/dtao/pool/latest/v1", 404)
    event["logger"] = "uvicorn.error"
    assert before_send(event, {}) is None


def test_drop_taostats_pool_latest_404_no_logger():
    event = _taostats_event("/dtao/pool/latest/v1", 404)
    del event["logger"]
    assert before_send(event, {}) is None


def test_retain_taostats_pool_latest_500():
    event = _taostats_event("/dtao/pool/latest/v1", 500)
    assert before_send(event, {}) is not None


def test_retain_taostats_pool_latest_500_body_mentions_404():
    event = _taostats_event("/dtao/pool/latest/v1", 500, "upstream 404 cached")
    assert before_send(event, {}) is not None


def test_retain_other_taostats_404():
    event = _taostats_event("/other/path", 404)
    result = before_send(event, {})
    assert result is not None
    assert result["logentry"]["params"][0] == "/other/path"


def test_retain_other_taostats_404_body_mentions_pool_path():
    event = _taostats_event("/other/path", 404, "see /dtao/pool/latest/v1 docs")
    assert before_send(event, {}) is not None


def test_retain_non_taostats_404():
    event = {
        "logger": "server",
        "logentry": {
            "message": "upstream %s returned %d",
            "params": ("/api/foo", 404),
        },
    }
    assert before_send(event, {}) is not None


def test_retain_pump_alerts_timeout_warning():
    event = {
        "logger": "server",
        "level": "warning",
        "logentry": {
            "message": "pump-alerts timed out after %ds",
            "params": (12,),
        },
        "request": {"url": "http://test/api/pump-alerts"},
    }
    result = before_send(event, {})
    assert result is not None
    assert "pump-alerts" in result["logentry"]["message"]


def test_retain_daily_pick_warning():
    event = {
        "logger": "server",
        "logentry": {
            "message": "daily pick handler slow netuid=%s",
            "params": (118,),
        },
    }
    result = before_send(event, {})
    assert result is not None
    assert result["logentry"]["params"] == (118,)


def test_scrub_authorization_header():
    event = {
        "request": {
            "headers": {
                "Authorization": "Bearer secret-token-xyz",
                "Content-Type": "application/json",
            },
        },
    }
    scrubbed = _scrub_event(event)
    assert scrubbed["request"]["headers"]["Authorization"] == "[redacted]"
    assert scrubbed["request"]["headers"]["Content-Type"] == "application/json"


def test_scrub_cookies_and_handles():
    event = {
        "logentry": {"message": "telegram group @secretuser failed", "params": ()},
        "request": {
            "cookies": {"session": "abc"},
            "query_string": "token=secret",
        },
    }
    scrubbed = _scrub_event(event)
    assert "[redacted-handle]" in scrubbed["logentry"]["message"]
    assert scrubbed["request"]["cookies"]["session"] == "[redacted]"


def test_scrub_taostats_body_snippet_retained_event():
    event = _taostats_event("/other/endpoint", 500, "leak-body-content")
    scrubbed = before_send(event, {})
    assert scrubbed is not None
    body_param = scrubbed["logentry"]["params"][2]
    assert body_param == "[redacted]"


def test_malformed_event_does_not_crash():
    assert before_send({}, {}) == {}
    assert before_send({"logentry": None}, {}) == {"logentry": None}
    assert _is_known_taostats_pool_latest_404({"logger": "fetchers.taostats_client"}) is False


def test_scrub_preserves_diagnostic_context():
    event = {
        "logger": "server",
        "logentry": {
            "message": "resolver cycle timeout netuid=%s elapsed=%s",
            "params": (118, 45.2),
        },
    }
    scrubbed = before_send(event, {})
    assert scrubbed["logentry"]["params"] == (118, 45.2)


def test_logging_integration_uses_before_send(monkeypatch):
    captured: list[dict] = []

    def capture(event, hint):
        out = before_send(event, hint)
        if out is not None:
            captured.append(out)
        return out

    monkeypatch.setenv("SENTRY_DSN", "https://examplePublicKey@o0.ingest.sentry.io/0")
    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_sdk.init(
        dsn="https://examplePublicKey@o0.ingest.sentry.io/0",
        integrations=[
            LoggingIntegration(level=logging.INFO, event_level=logging.WARNING),
        ],
        before_send=capture,
        transport=lambda: None,
    )

    logging.getLogger("fetchers.taostats_client").warning(
        "TaoStats %s returned %d body=%s",
        "/dtao/pool/latest/v1",
        404,
        "noise",
    )
    logging.getLogger("server").warning("pump-alerts timed out after %ds", 12)
    sentry_sdk.get_client().flush()

    assert len(captured) == 1
    assert "pump-alerts" in captured[0]["logentry"]["message"]
