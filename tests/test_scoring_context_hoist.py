"""Telegram calibration must load conviction rows once per scoring batch."""

from unittest import mock


def test_enrich_scoring_market_context_calls_conviction_rows_once():
    from internal.council.scoring_context import enrich_scoring_market_context

    calls = {"n": 0}

    def fake_rows():
        calls["n"] += 1
        return [{"id": 1, "source": "telegram"}]

    with mock.patch(
        "internal.message_intel.rollup._conviction_rows", side_effect=fake_rows
    ), mock.patch(
        "internal.message_intel.calibration.calibration_health",
        return_value={"active": False, "withheld_reasons": ["disabled_by_environment"]},
    ):
        ctx = enrich_scoring_market_context({})
        assert calls["n"] == 1
        assert ctx["telegram_conviction_rows"] is not None
        assert ctx["telegram_calibration_health"]["active"] is False

        from internal.council.state_vector import score_subnet_for_day

        sn = {"netuid": 1, "name": "t", "emission": 1.0, "price": 1.0}
        score_subnet_for_day(sn, ctx)
        score_subnet_for_day(sn, ctx)
    assert calls["n"] == 1
