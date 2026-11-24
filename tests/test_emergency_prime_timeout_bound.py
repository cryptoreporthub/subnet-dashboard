"""_prime_emergency_home_html must return within its 8s budget even if the render hangs."""

import threading
import time

import server as srv

BUDGET_SEC = 8.0
SLACK_SEC = 1.0


def test_prime_emergency_home_html_returns_within_budget_when_render_hangs(monkeypatch):
    release = threading.Event()

    def _hang(_request):
        release.wait(BUDGET_SEC + 4.0)
        return {}

    monkeypatch.setattr(srv, "_minimal_index_context", _hang)
    monkeypatch.setattr(srv, "_EMERGENCY_HOME_HTML", "")

    t0 = time.monotonic()
    try:
        html = srv._prime_emergency_home_html()
    finally:
        elapsed = time.monotonic() - t0
        release.set()

    assert html
    assert elapsed < BUDGET_SEC + SLACK_SEC, f"returned after {elapsed:.1f}s, budget {BUDGET_SEC}s"
