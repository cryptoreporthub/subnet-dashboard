"""Homepage hydration smoke contract.

This deliberately runs with the repository's cold/local defaults: no Telegram
credentials and no live subnet feed are required. It protects the fast shell
and the client hydration hand-off, not live data availability.
"""

from fastapi.testclient import TestClient

from server import app


def test_homepage_hydration_smoke(monkeypatch):
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)
    monkeypatch.setenv("DISABLE_BACKGROUND_SCANS", "1")

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.text.strip()
    assert len(response.text) > 1000
    assert "dataset.hydrate" in response.text
    assert "cockpit_hydrate.js" in response.text
    assert 'id="tribunal-hero"' in response.text
    assert 'id="section-picks"' in response.text or "section-picks" in response.text
    assert 'id="message-intel-feed"' in response.text
    assert "Loading council" not in response.text


def test_homepage_hydration_smoke_is_honest_without_live_sources(monkeypatch):
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)
    monkeypatch.setenv("DISABLE_BACKGROUND_SCANS", "1")

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith("text/html")
    # The shell must be usable before live APIs hydrate it; no Telegram/live
    # feed assertion belongs in this cold-start test.
    assert "hydrate" in response.text.lower()
