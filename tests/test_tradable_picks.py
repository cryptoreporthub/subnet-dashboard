"""Root / tradable universe + prediction attachment for council picks."""

from internal.council.daily_pick import select_daily_pick
from internal.council.hourly_pick import select_hourly_pick
from internal.council.red_team import audit_daily_pick
from internal.subnets.tradable import (
    is_tradable_subnet,
    normalize_subnet_row,
    subnet_netuid,
    tradable_subnets,
)


def _sample(netuid: int = 1, **overrides) -> dict:
    return {
        "netuid": netuid,
        "name": f"SN{netuid}",
        "symbol": f"SN{netuid}",
        "emission": 2.0,
        "apy": 40.0,
        "volume": 600_000,
        "market_cap": 15_000_000,
        "price": 10.0,
        "price_change_24h": 8.0,
        "price_change_7d": 15.0,
        "price_change_30d": 30.0,
        "status": "active",
        **overrides,
    }


def test_subnet_netuid_from_registry_id():
    row = normalize_subnet_row({"id": 7, "name": "X"})
    assert row["netuid"] == 7
    assert subnet_netuid({"id": 0, "name": "Root"}) == 0


def test_root_is_not_tradable():
    assert not is_tradable_subnet({"id": 0, "name": "Root"})
    assert not is_tradable_subnet({"netuid": 0, "name": "Root"})
    assert not is_tradable_subnet({"name": "Missing"})
    assert is_tradable_subnet({"netuid": 1, "name": "Apex"})


def test_tradable_subnets_drops_root_and_dedupes():
    rows = [
        {"id": 0, "name": "Root", "emission": 99},
        {"id": 1, "name": "Apex", "emission": 1},
        {"netuid": 1, "name": "Apex-live", "emission": 2},
        {"name": "no-id"},
    ]
    out = tradable_subnets(rows)
    assert len(out) == 1
    assert out[0]["netuid"] == 1
    assert out[0]["name"] == "Apex-live"


def test_audit_rejects_root():
    root = _sample(netuid=0, name="Root")
    audit = audit_daily_pick(root, [root, _sample(1)])
    assert audit["approved"] is False
    assert audit["adjusted_confidence"] == 0.0
    assert any("tradable" in c.lower() for c in audit["concerns"])


def test_select_daily_pick_never_returns_root():
    root = _sample(netuid=0, name="Root", emission=99.0, volume=9_000_000, social_mentions=9999)
    weak = _sample(netuid=5, name="Weak", emission=0.1, volume=200_000, price_change_24h=-1.0)
    strong = _sample(netuid=19, name="Inference", emission=2.0, volume=900_000)
    pick = select_daily_pick([root, weak, strong])
    assert pick["subnet"] is not None
    assert pick["subnet"]["netuid"] != 0
    assert pick["subnet"]["name"] != "Root"
    assert pick.get("prediction") is not None
    assert "predicted to move" in pick["prediction"]["statement"]
    assert 1 <= pick["prediction"]["horizon_hours"] <= 4


def test_select_hourly_pick_never_returns_root():
    root = _sample(netuid=0, name="Root", emission=99.0, volume=9_000_000)
    other = _sample(netuid=12, name="Compute")
    pick = select_hourly_pick([root, other])
    assert pick["subnet"]["netuid"] == 12


def test_select_daily_pick_empty_after_root_only():
    pick = select_daily_pick([_sample(netuid=0, name="Root")])
    assert pick["subnet"] is None
    assert pick["final_confidence"] == 0.0
