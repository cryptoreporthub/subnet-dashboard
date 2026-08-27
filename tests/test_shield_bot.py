"""Shield bot: four monitors, Policy §3.1 risk classes, no auto-block."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from internal.bots.shield import RISK_CLASSES, ShieldBot, run_shield
from internal.ops.notify import recent_records, reset_records


NOW = datetime(2026, 8, 27, 12, 0, 0, tzinfo=timezone.utc)


def _ts(seconds: int) -> str:
    return (NOW - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _event(
    *,
    ip: str,
    path: str,
    method: str = "GET",
    status: int = 200,
    seconds_ago: int = 0,
    ua: str | None = "Mozilla/5.0",
    accept: str | None = "application/json",
    authorization: str | None = None,
    extra_headers: dict | None = None,
    error: str | None = None,
    xff: str | None = None,
) -> dict:
    headers = {}
    if ua is not None:
        headers["User-Agent"] = ua
    if accept is not None:
        headers["Accept"] = accept
    if authorization is not None:
        headers["Authorization"] = authorization
    if xff:
        headers["X-Forwarded-For"] = xff
    if extra_headers:
        headers.update(extra_headers)
    row = {
        "ts": _ts(seconds_ago),
        "ip": ip,
        "method": method,
        "path": path,
        "status": status,
        "headers": headers,
    }
    if error:
        row["error"] = error
    return row


def setup_function() -> None:
    reset_records()


def test_honest_empty_when_logs_missing():
    report = run_shield(None, now=NOW)
    assert report["bot"] == "shield"
    assert report["status"] == "degraded"
    assert report["findings"] == []
    assert report["overall_risk"] is None
    assert report["remediations"] == []
    assert report["freshness"]["status"] in ("missing", "degraded")
    assert report["confidence"] is None
    assert report["mutated"] is False
    assert report["blocked"] is False
    assert "request_logs_unavailable" in report["unknowns"]
    events = [row["event"] for row in recent_records() if row["bot"] == "shield"]
    assert "scan_start" in events
    assert "scan_end" in events
    assert events.count("skip") == 4


def test_empty_iterable_is_observed_not_fabricated():
    report = run_shield([], now=NOW)
    assert report["findings"] == []
    assert report["overall_risk"] is None
    assert report["freshness"]["status"] != "missing"
    assert report["status"] == "ok"


def test_rate_limit_burst_is_low(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DEFAULT", "5/minute")
    events = [
        _event(ip="203.0.113.10", path="/api/registry", status=429, seconds_ago=3),
        _event(ip="203.0.113.10", path="/api/registry", status=429, seconds_ago=2),
        _event(ip="203.0.113.10", path="/api/summary", status=429, seconds_ago=1),
    ]
    report = run_shield(events, now=NOW)
    rate = [f for f in report["findings"] if f["monitor"] == "rate_limits"]
    assert rate
    assert rate[0]["risk"] == "low"
    assert rate[0]["confidence"] == report["confidence"] or rate[0]["confidence"] >= 0.05
    assert 0.0 <= rate[0]["confidence"] <= 1.0
    assert rate[0]["approval"]["action_category"] == "security"
    assert rate[0]["approval"]["status"] == "pending"
    assert rate[0]["recommended_action"]["auto_applied"] is False


def test_rate_limit_sustained_is_medium(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DEFAULT", "5/minute")
    events = []
    for minute in (0, 1):
        for i in range(6):
            events.append(
                _event(
                    ip="203.0.113.11",
                    path="/api/registry",
                    seconds_ago=minute * 60 + i,
                    status=200,
                )
            )
    report = run_shield(events, now=NOW)
    rate = [f for f in report["findings"] if f["monitor"] == "rate_limits"]
    assert rate
    assert rate[0]["risk"] == "medium"
    assert rate[0]["evidence"]["over_minute_windows"] >= 2


def test_scraping_enumeration_and_missing_headers():
    events = [
        _event(
            ip="198.51.100.20",
            path=f"/api/subnet/{n}",
            ua=None,
            accept=None,
            seconds_ago=n,
        )
        for n in range(1, 12)
    ]
    report = run_shield(events, now=NOW)
    scraping = [f for f in report["findings"] if f["monitor"] == "scraping"]
    assert scraping
    assert scraping[0]["risk"] in ("medium", "high")
    assert scraping[0]["evidence"]["max_enumeration"] >= 8
    assert 0.0 <= scraping[0]["confidence"] <= 1.0


def test_scraping_crawler_ua_needs_review_not_dropped():
    events = [
        _event(
            ip="198.51.100.21",
            path="/api/registry",
            ua="python-requests/2.32",
            seconds_ago=i,
        )
        for i in range(6)
    ]
    report = run_shield(events, now=NOW)
    scraping = [f for f in report["findings"] if f["monitor"] == "scraping"]
    assert scraping
    assert scraping[0]["risk"] == "low"
    assert scraping[0]["needs_review"] is True
    assert "false_positive_candidate" in (scraping[0]["needs_review_reason"] or "")


def test_endpoint_misuse_method_mismatch_is_low():
    events = [
        _event(ip="192.0.2.40", path="/api/whales/scan", method="GET", status=405),
        _event(ip="192.0.2.40", path="/health", method="POST", status=405),
    ]
    report = run_shield(events, now=NOW)
    misuse = [f for f in report["findings"] if f["monitor"] == "endpoint_misuse"]
    assert misuse
    assert misuse[0]["risk"] == "low"


def test_endpoint_misuse_scan_trigger_is_high():
    events = [
        _event(ip="192.0.2.41", path="/api/whales/scan", method="POST", status=200, seconds_ago=3),
        _event(ip="192.0.2.41", path="/api/ruggers/scan", method="POST", status=200, seconds_ago=2),
        _event(ip="192.0.2.41", path="/api/learning/trigger", method="POST", status=200, seconds_ago=1),
    ]
    report = run_shield(events, now=NOW)
    misuse = [f for f in report["findings"] if f["monitor"] == "endpoint_misuse"]
    assert misuse
    assert misuse[0]["risk"] == "high"
    assert misuse[0]["recommended_action"]["auto_applied"] is False


def test_endpoint_misuse_path_probe_is_medium():
    events = [
        _event(ip="192.0.2.42", path="/.env", status=404),
        _event(ip="192.0.2.42", path="/admin", status=404),
    ]
    report = run_shield(events, now=NOW)
    misuse = [f for f in report["findings"] if f["monitor"] == "endpoint_misuse"]
    assert misuse
    assert misuse[0]["risk"] == "medium"


def test_auth_abuse_clustered_401s_are_high(monkeypatch):
    monkeypatch.setenv("WRITE_API_TOKEN", "unit-test-token")
    events = [
        _event(
            ip="192.0.2.50",
            path="/api/learning/trigger",
            method="POST",
            status=401,
            authorization="Bearer wrong",
            error="write_api_token_required",
            seconds_ago=i,
        )
        for i in range(4)
    ]
    report = run_shield(events, now=NOW)
    auth = [f for f in report["findings"] if f["monitor"] == "auth_abuse"]
    assert auth
    assert auth[0]["risk"] == "high"
    assert "Bearer wrong" not in str(report)


def test_auth_abuse_credential_stuffing_is_critical_but_read_only(monkeypatch):
    monkeypatch.setenv("WRITE_API_TOKEN", "unit-test-token")
    events = [
        _event(
            ip="192.0.2.51",
            path="/api/message-intel/ingest",
            method="POST",
            status=401,
            authorization=f"Bearer guess-{i}",
            error="write_api_token_required",
            seconds_ago=i,
        )
        for i in range(12)
    ]
    before_token = "unit-test-token"
    report = run_shield(events, now=NOW)
    auth = [f for f in report["findings"] if f["monitor"] == "auth_abuse"]
    assert auth
    assert auth[0]["risk"] == "critical"
    assert report["overall_risk"] == "critical"
    assert report["mutated"] is False
    assert report["blocked"] is False
    assert auth[0]["mutated"] is False
    assert auth[0]["blocked"] is False
    assert auth[0]["recommended_action"]["auto_applied"] is False
    assert report["approval"]["required"] is True
    assert report["approval"]["status"] == "pending"
    assert report["approval"]["approver_role"] == "security_operator"
    assert report["approval"]["surface"] == "security_review_queue"
    for item in report["remediations"]:
        assert item["auto_applied"] is False
        assert item["approval"]["status"] == "pending"
    import os

    assert os.environ.get("WRITE_API_TOKEN") == before_token
    blob = str(report)
    assert "guess-0" not in blob
    assert "unit-test-token" not in blob


def test_four_risk_classes_and_per_finding_confidence(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DEFAULT", "5/minute")
    monkeypatch.setenv("WRITE_API_TOKEN", "unit-test-token")
    events = []
    # low: burst 429s
    events.extend(
        [
            _event(ip="203.0.113.10", path="/api/registry", status=429, seconds_ago=2),
            _event(ip="203.0.113.10", path="/api/registry", status=429, seconds_ago=1),
        ]
    )
    # medium: path probe
    events.append(_event(ip="192.0.2.42", path="/.env", status=404, seconds_ago=4))
    # high: clustered 401s
    events.extend(
        [
            _event(
                ip="192.0.2.50",
                path="/api/learning/trigger",
                method="POST",
                status=401,
                authorization="Bearer x",
                error="write_api_token_required",
                seconds_ago=10 + i,
            )
            for i in range(4)
        ]
    )
    # critical: stuffing
    events.extend(
        [
            _event(
                ip="192.0.2.51",
                path="/api/learning/trigger",
                method="POST",
                status=401,
                authorization=f"Bearer stuff-{i}",
                error="write_api_token_required",
                seconds_ago=20 + i,
            )
            for i in range(10)
        ]
    )
    report = run_shield(events, now=NOW)
    seen = {f["risk"] for f in report["findings"]}
    assert seen == set(RISK_CLASSES) or seen >= {"low", "medium", "high", "critical"}
    for name in RISK_CLASSES:
        assert name in seen
    for finding in report["findings"]:
        assert finding["risk"] in RISK_CLASSES
        assert "info" not in finding["risk"]
        assert isinstance(finding["confidence"], float)
        assert 0.0 <= finding["confidence"] <= 1.0
    assert report["confidence"] == min(f["confidence"] for f in report["findings"])


def test_needs_review_when_freshness_degraded():
    events = [
        _event(
            ip="198.51.100.20",
            path=f"/api/subnet/{n}",
            ua=None,
            accept=None,
            seconds_ago=4000 + n,
        )
        for n in range(1, 12)
    ]
    stale = run_shield(events, now=NOW)
    scraping = [f for f in stale["findings"] if f["monitor"] == "scraping"]
    assert scraping
    assert stale["freshness"]["status"] == "stale"
    assert scraping[0]["needs_review"] is True
    assert "stale_evidence" in (scraping[0]["needs_review_reason"] or "")

    timeless = [
        {
            "ip": "198.51.100.99",
            "method": "GET",
            "path": f"/api/subnet/{n}",
            "status": 200,
            "headers": {},
        }
        for n in range(1, 12)
    ]
    uncertain = run_shield(timeless, now=NOW)
    scraping = [f for f in uncertain["findings"] if f["monitor"] == "scraping"]
    assert scraping
    assert uncertain["freshness"]["status"] == "degraded"
    assert scraping[0]["needs_review"] is True
    assert scraping[0]["needs_review_reason"]


def test_notify_logs_start_detections_skips_recommendations_end(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DEFAULT", "5/minute")
    events = [
        _event(ip="203.0.113.10", path="/api/registry", status=429, seconds_ago=1),
        _event(ip="203.0.113.10", path="/api/registry", status=429, seconds_ago=0),
    ]
    report = ShieldBot().scan(events, now=NOW)
    kinds = [row["event"] for row in recent_records() if row["run_id"] == report["run_id"]]
    assert kinds[0] == "scan_start"
    assert kinds[-1] == "scan_end"
    assert "detection" in kinds
    assert "recommendation" in kinds
    assert "skip" in kinds
    assert report["audit"]["ids"]
    assert len(report["audit"]["ids"]) == len(kinds)


def test_redacts_authorization_from_report_and_audit():
    events = [
        _event(
            ip="192.0.2.50",
            path="/api/learning/trigger",
            method="POST",
            status=401,
            authorization="Bearer super-secret-token",
            extra_headers={"X-Write-Api-Token": "header-secret"},
            error="write_api_token_required",
        )
    ]
    report = run_shield(events, now=NOW)
    dumped = str(report)
    assert "super-secret-token" not in dumped
    assert "header-secret" not in dumped
    for row in recent_records():
        assert "super-secret-token" not in str(row)
        assert "header-secret" not in str(row)


def test_fly_xff_first_hop_is_the_client_key(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DEFAULT", "5/minute")
    events = [
        _event(
            ip="0.0.0.0",
            xff="203.0.113.77, 10.0.0.1",
            path="/api/registry",
            status=429,
            seconds_ago=1,
        ),
        _event(
            ip="0.0.0.0",
            xff="203.0.113.77, 10.0.0.1",
            path="/api/registry",
            status=429,
            seconds_ago=0,
        ),
    ]
    report = run_shield(events, now=NOW)
    rate = [f for f in report["findings"] if f["monitor"] == "rate_limits"]
    assert rate
    assert rate[0]["subject"]["ip"] == "203.0.113.77"


def test_cli_honest_empty(capsys):
    from internal.bots.shield import main

    assert main([]) == 0
    out = capsys.readouterr().out
    assert '"bot": "shield"' in out
    assert '"findings": []' in out


def test_mixed_timestamps_are_degraded_and_reviewed():
    events = [
        _event(
            ip="198.51.100.30",
            path=f"/api/subnet/{n}",
            ua=None,
            accept=None,
            seconds_ago=n,
        )
        for n in range(1, 10)
    ]
    events.append(
        {
            "ip": "198.51.100.30",
            "method": "GET",
            "path": "/api/subnet/99",
            "status": 200,
            "headers": {},
        }
    )
    events.append("not-a-row")
    report = run_shield(events, now=NOW)
    assert report["freshness"]["status"] == "degraded"
    assert any(u.startswith("untimestamped_rows:") for u in report["unknowns"])
    assert any(u.startswith("unreadable_rows:") for u in report["unknowns"])
    scraping = [f for f in report["findings"] if f["monitor"] == "scraping"]
    assert scraping
    assert scraping[0]["needs_review"] is True


def test_method_mismatch_is_flagged_for_review():
    events = [
        _event(ip="192.0.2.40", path="/api/whales/scan", method="GET", status=405),
    ]
    report = run_shield(events, now=NOW)
    misuse = [f for f in report["findings"] if f["monitor"] == "endpoint_misuse"]
    assert misuse
    assert misuse[0]["needs_review"] is True
    assert "false_positive_candidate" in (misuse[0]["needs_review_reason"] or "")


def test_scan_exception_emits_scan_end_without_leaking():
    def _boom():
        yield _event(ip="192.0.2.9", path="/api/registry")
        raise RuntimeError("Authorization: Bearer leaked-on-error")

    report = run_shield(_boom(), now=NOW)
    assert report["status"] == "degraded"
    assert report["findings"] == []
    assert "scan_error" in report["unknowns"]
    assert "leaked-on-error" not in str(report)
    kinds = [row["event"] for row in recent_records() if row["run_id"] == report["run_id"]]
    assert kinds[0] == "scan_start"
    assert kinds[-1] == "scan_end"
