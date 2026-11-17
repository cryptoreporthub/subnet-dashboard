"""Pump/merge must not run full Blockmachine merge during live_subnets sync."""

from unittest.mock import MagicMock, patch


def test_get_merged_subnet_data_skips_blockmachine_during_live_subnets_sync():
    from fetchers import merged_data

    quick_rows = [{"netuid": 7, "price": 1.0, "source": "taomarketcap"}]
    chain_called = {"n": 0}

    class _Client:
        def is_healthy(self):
            return True

        def get_all_subnet_data(self):
            chain_called["n"] += 1
            return [{"netuid": 99, "price": 2.0}]

    with (
        patch.object(merged_data, "_get_cached", return_value=None),
        patch.object(merged_data, "get_merged_subnet_rows_quick", return_value=quick_rows),
        patch(
            "internal.live_subnets.live_subnets_sync_in_progress",
            return_value=True,
        ),
        patch(
            "internal.chain_client.get_default_client",
            return_value=_Client(),
        ),
        patch(
            "fetchers.taomarketcap.get_all_subnets",
            MagicMock(side_effect=AssertionError("TMC should not run")),
        ),
    ):
        out = merged_data.get_merged_subnet_data()

    assert out == quick_rows
    assert chain_called["n"] == 0
