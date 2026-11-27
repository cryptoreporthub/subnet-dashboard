"""#1640: mindmap _STATE_CACHE lock, degraded isolation, last-good, generation fence."""

from __future__ import annotations

import threading
import time

from internal.council import weights as council_weights
from internal.learning import mindmap_aggregator as agg
from internal.learning import panel_summaries
from internal.learning.mindmap_aggregator import (
    build_mindmap_state,
    get_stale_mindmap_state,
    reset_mindmap_state_cache,
)

_COUNCIL_LOAD_ERROR = (
    "Council expert weights could not load right now; expert influence is not shown."
)


def _expire_fresh_cache() -> None:
    """Force a TTL miss without wiping last-good stale state."""
    with agg._STATE_CACHE_LOCK:
        agg._STATE_CACHE["at"] = 0.0
        agg._STATE_CACHE["payload"] = None


def test_degraded_build_not_cached_and_preserves_last_good_stale_state(monkeypatch):
    healthy = build_mindmap_state()
    healthy_council = (healthy.get("summaries") or {}).get("council", {}).get("text", "")
    assert healthy_council
    assert _COUNCIL_LOAD_ERROR not in healthy_council

    _expire_fresh_cache()

    def _boom():
        raise council_weights.ConcurrentWeightUpdate("stale weight map")

    monkeypatch.setattr(council_weights, "load_weights", _boom)
    degraded = build_mindmap_state()
    degraded_text = (degraded.get("summaries") or {}).get("council", {}).get("text", "")
    assert "could not load" in degraded_text
    assert agg._STATE_CACHE["payload"] is None

    stale = get_stale_mindmap_state()
    assert stale is not None
    assert (stale.get("summaries") or {}).get("council", {}).get("text") == healthy_council

    monkeypatch.undo()
    recovered = build_mindmap_state()
    recovered_council = (recovered.get("summaries") or {}).get("council", {}).get("text", "")
    assert recovered_council
    assert _COUNCIL_LOAD_ERROR not in recovered_council
    assert agg._STATE_CACHE["payload"] is not None


def test_miss_return_copy_prevents_inplace_cache_corruption():
    _expire_fresh_cache()
    payload = build_mindmap_state()
    assert payload.get("status") == "success"
    payload["status"] = "mutated"
    again = build_mindmap_state()
    assert again.get("status") == "success"


def test_reset_generation_fence_drops_inflight_pre_reset_build(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def _slow_council():
        started.set()
        assert release.wait(timeout=5)
        return {"text": "late", "sentences": ["late"]}

    _expire_fresh_cache()
    monkeypatch.setattr(agg, "collect_trail_events", lambda limit=200: [])
    monkeypatch.setattr(panel_summaries, "summarize_council", _slow_council)
    holder: dict = {}

    def _run():
        holder["payload"] = build_mindmap_state()

    thread = threading.Thread(target=_run)
    thread.start()
    assert started.wait(timeout=5)
    reset_mindmap_state_cache()
    release.set()
    thread.join(timeout=5)
    assert thread.is_alive() is False
    assert agg._STATE_CACHE["payload"] is None
    assert get_stale_mindmap_state() is None
    assert holder.get("payload") is not None


def test_concurrent_builders_and_reset_no_errors():
    errors: list = []
    deadline = time.monotonic() + 0.5

    def _builder():
        try:
            while time.monotonic() < deadline:
                payload = build_mindmap_state()
                if not isinstance(payload, dict) or "status" not in payload:
                    errors.append(f"torn payload: {payload!r}")
                    return
        except Exception as exc:
            errors.append(exc)

    def _resetter():
        try:
            while time.monotonic() < deadline:
                reset_mindmap_state_cache()
                stale = get_stale_mindmap_state()
                if stale is not None and not isinstance(stale, dict):
                    errors.append(f"torn stale: {stale!r}")
                    return
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=_builder),
        threading.Thread(target=_builder),
        threading.Thread(target=_resetter),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=8)
    assert all(not t.is_alive() for t in threads)
    assert errors == []


def test_reset_mindmap_state_cache_clears_both_fresh_and_stale():
    payload = build_mindmap_state()
    assert payload.get("status") == "success"
    assert agg._STATE_CACHE.get("payload") is not None
    assert get_stale_mindmap_state() is not None
    reset_mindmap_state_cache()
    assert agg._STATE_CACHE.get("payload") is None
    assert get_stale_mindmap_state() is None
    assert agg._STATE_CACHE.get("at") == 0.0
