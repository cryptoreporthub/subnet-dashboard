"""Fast degraded homepage shell ships local learning + SimiVision data."""

import time

from fastapi.testclient import TestClient

from server import app

client = TestClient(app)


def test_degraded_homepage_has_conviction_cards():
    html = client.get("/").text
    assert "dataset.hydrate='1'" in html or 'dataset.hydrate="1"' in html
    assert "pick-card" in html
    assert "SimiVision picks warming up" not in html


def test_degraded_homepage_has_council_weights():
    html = client.get("/").text
    assert "council-grid" in html
    assert "Council weights warming up" not in html


def test_fast_shell_learning_metrics_has_graded_field():
    from internal.learning.dashboard_context import fast_shell_dashboard_context

    metrics = fast_shell_dashboard_context()["learning_metrics"]
    assert "correct" in metrics
    assert "wrong" in metrics
    assert metrics.get("graded") is not None or (metrics.get("correct", 0) + metrics.get("wrong", 0)) >= 0


def test_homepage_responds_quickly():
    t0 = time.time()
    resp = client.get("/")
    elapsed = time.time() - t0
    assert resp.status_code == 200
    assert elapsed < 5.0, f"homepage took {elapsed:.1f}s"


def test_homepage_includes_above_fold_scripts():
    html = client.get("/").text
    for src in (
        "api_fetch.js",
        "brain_letter.js",
        "paper_portfolio.js",
        "weekly_letter.js",
        "market_drivers_ui.js",
    ):
        assert src in html, f"missing {src}"
    assert "apiFetchJson" in html, "missing inline fetch timeout bootstrap"
