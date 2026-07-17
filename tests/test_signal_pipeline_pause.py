"""Signal pipeline should not score on stale registry zeros."""

from internal.signals.pipeline import generate_signals, load_subnets


def test_load_subnets_skips_unpriced_registry_fallback(monkeypatch):
    """When live feed has no price deltas, return empty (honest pause)."""
    monkeypatch.setattr(
        "fetchers.taomarketcap.get_all_subnets",
        lambda: [{"netuid": 1, "name": "A", "price": 0, "price_change_24h": 0}],
    )
    rows = load_subnets()
    assert rows == []


def test_generate_signals_paused_when_no_live_subnets(monkeypatch):
    monkeypatch.setattr("internal.signals.pipeline.load_subnets", lambda: [])
    out = generate_signals(persist=False)
    assert out["status"] == "paused"
    assert out["meta"]["reason"] == "live_price_feed_unavailable"
    assert out["signals"] == []
