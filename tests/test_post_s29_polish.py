"""§29 polish tests."""

from unittest.mock import patch


def test_wallet_rug_flags_from_exposure():
    from internal.share_pages.routes import _wallet_rug_flags

    with patch("internal.ruggers.watchlist.RuggerWatchlist.get_subnet_risk") as mock_risk:
        mock_risk.return_value = {"risk_level": "high", "rugger_count": 2}
        flags = _wallet_rug_flags([{"netuid": 1, "amount_tao": 10.0}])
    assert len(flags) == 1
    assert flags[0]["netuid"] == 1
    assert flags[0]["risk_level"] == "high"


def test_load_pick_subnets_uses_feed(monkeypatch):
    from internal.subnets.feed import load_pick_subnets

    monkeypatch.setattr(
        "internal.subnets.feed.get_council_subnet_feed",
        lambda: ([{"netuid": 3, "name": "Gamma"}], "taomarketcap"),
    )
    rows = load_pick_subnets()
    assert rows[0]["netuid"] == 3


def test_rugger_subnet_risk_level():
    from internal.ruggers.watchlist import RuggerWatchlist

    class FakeService:
        def get_subnet_flow(self, netuid):
            return {
                "data_available": True,
                "by_classification": {"ruggers": [{"wallet": "x"}]},
                "avoid_follow": False,
            }

    watch = RuggerWatchlist(service=FakeService())
    risk = watch.get_subnet_risk(7)
    assert risk["risk_level"] == "medium"
