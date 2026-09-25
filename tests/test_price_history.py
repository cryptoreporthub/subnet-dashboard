"""Local BM price history — deltas and derived rank."""

from datetime import datetime, timedelta, timezone

from internal.subnets.price_history import compute_price_changes, enrich_rows


def test_compute_price_changes_24h():
    store = {
        "subnets": {
            "5": {
                "samples": [
                    {"ts": "2026-09-24T12:00:00+00:00", "price": 100.0},
                    {"ts": "2026-09-25T12:00:00+00:00", "price": 110.0},
                ]
            }
        }
    }
    now = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
    changes = compute_price_changes(5, now=now, store=store)
    assert changes["price_change_24h"] == 10.0


def test_enrich_rows_assigns_rank_without_overwriting_tmc(monkeypatch):
    now = datetime.now(timezone.utc)
    day_ago = (now - timedelta(hours=24)).isoformat()
    store = {
        "subnets": {
            "1": {
                "samples": [
                    {"ts": day_ago, "price": 1.0},
                    {"ts": now.isoformat(), "price": 2.0},
                ]
            },
            "2": {
                "samples": [
                    {"ts": day_ago, "price": 0.5},
                    {"ts": now.isoformat(), "price": 1.0},
                ]
            },
        }
    }
    monkeypatch.setattr("internal.subnets.price_history._load_store", lambda: store)
    rows = [
        {"netuid": 1, "price": 2.0, "total_alpha": 100, "price_change_24h": 99.0},
        {"netuid": 2, "price": 1.0, "total_alpha": 500},
    ]
    out = enrich_rows(rows)
    by_uid = {r["netuid"]: r for r in out}
    assert by_uid[1]["price_change_24h"] == 99.0  # TMC value kept
    assert by_uid[2]["price_change_24h"] is not None
    assert by_uid[2]["marketcap_rank"] == 1
    assert by_uid[1]["marketcap_rank"] == 2
