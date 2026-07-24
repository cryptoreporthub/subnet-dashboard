"""Macro signals from subnet integration clients."""

from __future__ import annotations

from unittest.mock import patch

from internal.integrations.signals import build_macro_signals


def test_build_macro_signals_numinous_leaderboard():
    def fake_probe(method, url, **kwargs):
        if "numinouslabs" in url:
            return True, 200, '{"results":[{"miner_uid":7,"weight":0.2}]}'
        if "llms_txt_store" in url:
            return True, 200, "# Stripe\n> Payments\n"
        return False, 0, ""

    with patch("internal.integrations.signals._http_probe", side_effect=fake_probe):
        payload = build_macro_signals()
    assert payload["signal_count"] >= 2
    slugs = {s["slug"] for s in payload["signals"]}
    assert "numinous" in slugs
    assert "readyai" in slugs
