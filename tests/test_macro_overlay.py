"""Macro overlay wiring into council scoring."""

from __future__ import annotations

from internal.integrations.macro_overlay import apply_macro_score_overlay, build_macro_overlay


def test_macro_overlay_tailwind_from_synth():
    payload = {
        "mood": "forecast_available",
        "signal_count": 1,
        "signals": [{"slug": "synth", "data": {"note": "bullish above 60k"}}],
    }
    from internal.integrations.macro_overlay import _tailwind_from_signals

    mood, tailwind, sources = _tailwind_from_signals(payload)
    assert "synth" in sources
    assert tailwind > 0
    assert "bull" in mood or tailwind > 0


def test_apply_macro_score_overlay_adjusts_total():
    ctx = {
        "macro_overlay": {
            "alpha": 0.10,
            "tailwind": 2.0,
            "mood": "bullish_tailwind",
            "sources": ["synth"],
        }
    }
    out, meta = apply_macro_score_overlay(50.0, ctx)
    assert out > 50.0
    assert meta is not None
    assert meta["sources"] == ["synth"]


def test_build_macro_overlay_caches(monkeypatch):
    calls = {"n": 0}

    def fake_signals():
        calls["n"] += 1
        return {"mood": "neutral", "signals": [], "signal_count": 0}

    monkeypatch.setattr(
        "internal.integrations.signals.build_macro_signals",
        fake_signals,
    )
    import internal.integrations.macro_overlay as mo

    mo._CACHE["at"] = 0
    mo._CACHE["overlay"] = {}
    build_macro_overlay(force=True)
    build_macro_overlay()
    assert calls["n"] == 1
