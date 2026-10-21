"""Rate-limit counters must not leak from one test into the next (they produced spurious 429s)."""

from fastapi.testclient import TestClient

from server import app

STRICT_BURST = 31  # strict limit is 30/minute per client IP


def test_first_test_exhausts_the_strict_limit():
    with TestClient(app) as client:
        codes = [client.post("/api/mindmap/feedback", json={}).status_code for _ in range(STRICT_BURST)]
    assert codes[-1] == 429, "limiter inactive: this isolation check would prove nothing"


def test_next_test_starts_with_a_clean_budget():
    """Runs after the test above in the same process; the counter must have been reset."""
    with TestClient(app) as client:
        assert client.post("/api/mindmap/feedback", json={}).status_code == 200
