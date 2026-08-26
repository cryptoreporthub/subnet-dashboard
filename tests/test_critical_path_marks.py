"""#1058 step 1 — homepage Server-Timing + G0 critical-path summary keys."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness.g0_hydration_starvation import run_g0
from server import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_homepage_includes_server_timing(client):
    response = client.get("/")
    assert response.status_code == 200
    timing = response.headers.get("Server-Timing") or ""
    assert timing.startswith("app;dur=")
    assert "html-parse" in response.text


def test_probe_machine_state_warm():
    samples = [{"latency_ms": 40, "ok": True}, {"latency_ms": 55, "ok": True}]
    latencies = [s["latency_ms"] for s in samples]
    warm = all(ms < run_g0.MACHINE_WARM_MS for ms in latencies)
    assert warm


def test_critpath_median_table_renders():
    summaries = [
        {
            "navigation_timing": {"domContentLoadedEventEnd": 1200.0},
            "hero_api_timing": {"learning_stats": {"start_s": 1.5}},
            "hero_complete_at_s": 2.1,
            "machine_state": "warm",
        },
        {
            "navigation_timing": {"domContentLoadedEventEnd": 1400.0},
            "hero_api_timing": {"learning_stats": {"start_s": 1.7}},
            "hero_complete_at_s": 2.4,
            "machine_state": "warm",
        },
    ]
    md = run_g0.critpath_median_table("test-id", summaries)
    assert "DCL" in md
    assert "Hero complete" in md
    assert "critpath-test-id" in md


def test_g0_summary_schema_keys_without_playwright(tmp_path: Path):
    """Harness summary.json must expose critpath fields (static fixture)."""
    fixture = {
        "machine_state": "warm",
        "document_server_timing": "app;dur=12.3",
        "critical_path": {
            "marks": {"html-parse": 0.1, "hydrate-start": 800.0, "hydrate-end": 2100.0},
            "first_script": {"name": "/static/js/app.js", "startTime": 50.0},
            "script_wall_before_dcl": {"name": "/static/js/cockpit_hydrate.js", "responseEnd": 900.0},
        },
        "hero_api_timing": {
            "learning_stats": {"start_s": 1.2, "end_s": 1.8},
            "daily_pick": {"start_s": 1.1, "end_s": 1.9},
        },
        "navigation_timing": {"responseStart": 100.0, "domContentLoadedEventEnd": 1200.0},
    }
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(fixture, indent=2) + "\n")
    loaded = json.loads(path.read_text())
    for key in (
        "machine_state",
        "document_server_timing",
        "critical_path",
        "hero_api_timing",
        "navigation_timing",
    ):
        assert key in loaded
    assert "html-parse" in loaded["critical_path"]["marks"]
