"""_maybe_investigation_context must return None within its budget when the builder hangs."""

import threading
import time

from internal.simivision import chat_service as chat

BUDGET_SEC = 1.0
SLACK_SEC = 1.0


def test_investigation_context_returns_within_budget_when_builder_hangs(monkeypatch):
    release = threading.Event()

    def _hang(*_a, **_k):
        release.wait(BUDGET_SEC + 4.0)
        return {"late": True}

    monkeypatch.setattr(chat, "build_investigation_context", _hang)
    monkeypatch.setattr(chat, "_INVESTIGATION_TIMEOUT_SEC", BUDGET_SEC)

    t0 = time.monotonic()
    try:
        result = chat._maybe_investigation_context("Investigate subnet 5 on-chain flows")
    finally:
        elapsed = time.monotonic() - t0
        release.set()

    assert result is None
    assert elapsed < BUDGET_SEC + SLACK_SEC, f"returned after {elapsed:.1f}s, budget {BUDGET_SEC}s"
