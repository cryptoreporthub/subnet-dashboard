"""Homepage hydration smoke contract.

The homepage has two supported cold-start outcomes: the normal shell, or the
small emergency shell used while the template/cache is being warmed. This test
checks the contract that is valid without Telegram credentials or live subnet
data without treating the emergency fallback as a failure.
"""

from fastapi.testclient import TestClient

from server import app


def _cold_homepage(monkeypatch):
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)
    monkeypatch.setenv("DISABLE_BACKGROUND_SCANS", "1")

    with TestClient(app) as client:
        return client.get("/")


def test_homepage_hydration_smoke(monkeypatch):
    response = _cold_homepage(monkeypatch)

    assert response.status_code == 200
    assert response.text.strip()
    assert response.headers.get("content-type", "").startswith("text/html")

    # Cold boot may legitimately return the emergency shell while the normal
    # homepage is being warmed. Validate either supported contract explicitly.
    if "dataset.hydrate" in response.text:
        assert "cockpit_hydrate.js" in response.text
        assert 'id="tribunal-hero"' in response.text
        assert "section-picks" in response.text
        assert 'id="message-intel-feed"' in response.text
        assert "Loading council" not in response.text
    else:
        assert "Loading council" in response.text
        assert "location.reload" in response.text


def test_homepage_hydration_smoke_is_honest_without_live_sources(monkeypatch):
    response = _cold_homepage(monkeypatch)

    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith("text/html")
    # The shell must be usable before live APIs hydrate it; no Telegram/live
    # feed assertion belongs in this cold-start test.
    assert "html" in response.text.lower()
