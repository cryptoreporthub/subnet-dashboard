import pytest
from fastapi.testclient import TestClient

from internal.judges.subnet_judges import score_all_subnets, score_subnet
from server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_score_subnet_shape():
    """score_subnet returns the expected dict shape with scores in [0,1]."""
    subnet = {
        "netuid": 1,
        "name": "Test",
        "price": 10.0,
        "apy": 0.5,
        "emission": 100.0,
        "stake": 1000.0,
        "volume": 500000.0,
        "price_change_24h": 5.0,
        "social_mentions": 10,
        "social_sentiment": 0.6,
    }
    result = score_subnet(1, subnet)
    assert result["netuid"] == 1
    assert result["name"] == "Test"
    for judge in ("oracle", "echo", "pulse"):
        assert judge in result
        assert 0 <= result[judge]["score"] <= 1
        assert 0 <= result[judge]["confidence"] <= 1
    assert "consensus" in result
    assert 0 <= result["consensus"]["score"] <= 1
    assert result["consensus"]["verdict"] in ("long", "short", "neutral")


def test_score_subnet_oracle_degrade():
    """Empty subnet fields mark Oracle as degraded."""
    subnet = {"netuid": 2, "name": "Empty"}
    result = score_subnet(2, subnet)
    assert result["oracle"]["degraded"] is True


def test_score_subnet_echo_degrade():
    """No social data marks Echo as degraded."""
    subnet = {"netuid": 3, "name": "NoSocial", "price_change_24h": 2.0, "volume": 1000}
    result = score_subnet(3, subnet)
    assert result["echo"]["degraded"] is True


class BrokenChainClient:
    """Simulate a chain client whose health check raises."""

    def is_healthy(self):
        raise RuntimeError("boom")


def test_score_subnet_pulse_degrade():
    """A failing chain client marks Pulse as degraded."""
    subnet = {"netuid": 4, "name": "BadChain", "price_change_24h": 2.0, "volume": 1000}
    result = score_subnet(4, subnet, chain_client=BrokenChainClient())
    assert result["pulse"]["degraded"] is True


def test_consensus_agreement(monkeypatch):
    """Identical judge scores yield high agreement; divergent scores are contested."""
    monkeypatch.setattr(
        "internal.judges.subnet_judges.ORACLE.evaluate",
        lambda *_a, **_k: {"score": 0.9, "confidence": 0.9},
    )
    monkeypatch.setattr(
        "internal.judges.subnet_judges.ECHO.evaluate",
        lambda *_a, **_k: {"score": 0.9, "confidence": 0.9},
    )
    monkeypatch.setattr(
        "internal.judges.subnet_judges.PULSE.evaluate",
        lambda *_a, **_k: {"score": 0.9, "confidence": 0.9},
    )
    agree = score_subnet(5, {"name": "Agree"})
    assert agree["consensus"]["agreement"] > 0.9
    assert agree["consensus"]["verdict"] == "long"
    assert agree["consensus"]["contested"] is False

    monkeypatch.setattr(
        "internal.judges.subnet_judges.ORACLE.evaluate",
        lambda *_a, **_k: {"score": 0.9, "confidence": 0.9},
    )
    monkeypatch.setattr(
        "internal.judges.subnet_judges.ECHO.evaluate",
        lambda *_a, **_k: {"score": 0.5, "confidence": 0.5},
    )
    monkeypatch.setattr(
        "internal.judges.subnet_judges.PULSE.evaluate",
        lambda *_a, **_k: {"score": 0.1, "confidence": 0.1},
    )
    diverge = score_subnet(6, {"name": "Diverge"})
    assert diverge["consensus"]["contested"] is True
    assert diverge["consensus"]["verdict"] == "neutral"


def test_api_judges_returns_200(client, monkeypatch):
    """GET /api/judges returns 200 and a judges list."""
    import server

    def _fake_subnets():
        return [
            {"netuid": 1, "name": "A", "price": 1.0, "apy": 0.1, "emission": 1.0, "volume": 1000000, "price_change_24h": 5.0, "social_mentions": 10, "social_sentiment": 0.6},
            {"netuid": 2, "name": "B", "price": 2.0, "apy": 0.2, "emission": 2.0, "volume": 2000000, "price_change_24h": 10.0, "social_mentions": 20, "social_sentiment": 0.7},
            {"netuid": 3, "name": "C", "price": 3.0, "apy": 0.3, "emission": 3.0, "volume": 3000000, "price_change_24h": 15.0, "social_mentions": 30, "social_sentiment": 0.8},
        ]

    monkeypatch.setattr(server, "get_all_subnets", _fake_subnets)
    server._refresh_judge_scores()
    response = client.get("/api/judges")
    assert response.status_code == 200
    data = response.json()
    assert "judges" in data
    assert len(data["judges"]) >= 3


def test_api_paper_portfolio_returns_200(client):
    """GET /api/paper-portfolio returns 200 with aggregate and judges."""
    response = client.get("/api/paper-portfolio")
    assert response.status_code == 200
    data = response.json()
    assert "aggregate" in data
    assert "judges" in data


def test_api_postmortems_returns_200(client):
    """GET /api/postmortems returns 200."""
    response = client.get("/api/postmortems")
    assert response.status_code == 200
    data = response.json()
    assert "postmortems" in data
