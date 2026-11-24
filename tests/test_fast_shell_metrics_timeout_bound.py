"""fast_shell_dashboard_context must not wait past its 2s learning-metrics budget."""

import threading
import time

from internal.learning import dashboard_context as dc

BUDGET_SEC = 2.0
SLACK_SEC = 1.0


def test_fast_shell_context_returns_within_budget_when_metrics_hang(monkeypatch):
    release = threading.Event()

    def _hang():
        release.wait(BUDGET_SEC + 4.0)
        raise RuntimeError("late")

    monkeypatch.setattr("internal.data_volume.needs_worker_volume_proxy", lambda: False)
    monkeypatch.setattr("internal.learning.routes._learning_snapshot", _hang)
    monkeypatch.setattr(dc, "load_weights_for_ui", lambda: {})
    monkeypatch.setattr(dc, "_FAST_SHELL_CACHE", {"at": 0.0, "data": None})

    t0 = time.monotonic()
    try:
        ctx = dc.fast_shell_dashboard_context()
    finally:
        elapsed = time.monotonic() - t0
        release.set()

    assert isinstance(ctx, dict)
    assert elapsed < BUDGET_SEC + SLACK_SEC, f"returned after {elapsed:.1f}s, budget {BUDGET_SEC}s"
