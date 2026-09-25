"""BM-first subnet feed tier order."""

import json
import os

from internal.subnets.feed import load_live_cache_rows, load_subnets_source


def test_load_live_cache_rows_reads_blockmachine_cache(tmp_path, monkeypatch):
    cache = tmp_path / "live_subnets.json"
    cache.write_text(
        json.dumps(
            {
                "synced_at": "2026-09-25T00:00:00+00:00",
                "source": "blockmachine",
                "count": 1,
                "subnets": [
                    {
                        "netuid": 7,
                        "name": "SN7",
                        "price": 0.5,
                        "source": "blockmachine",
                        "live": True,
                    }
                ],
            }
        )
    )
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    rows = load_live_cache_rows()
    assert len(rows) == 1
    assert rows[0]["netuid"] == 7
    assert rows[0].get("live") is True


def test_load_subnets_source_prefers_live_cache_over_tmc(monkeypatch, tmp_path):
    cache = tmp_path / "live_subnets.json"
    cache.write_text(
        json.dumps(
            {
                "synced_at": "2026-09-25T00:00:00+00:00",
                "source": "blockmachine",
                "count": 1,
                "subnets": [
                    {
                        "netuid": 9,
                        "name": "SN9",
                        "price": 1.0,
                        "source": "blockmachine",
                        "live": True,
                    }
                ],
            }
        )
    )
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr("internal.subnets.feed.load_subnets_snapshot_rows", lambda: [])

    def _tmc_should_not_run():
        raise AssertionError("TMC inner load must not run when live cache exists")

    monkeypatch.setattr("internal.subnets.feed._load_subnets_inner", _tmc_should_not_run)
    rows = load_subnets_source()
    assert rows and rows[0]["netuid"] == 9


def test_load_live_cache_rows_empty_when_no_live_bm(tmp_path, monkeypatch):
    cache = tmp_path / "live_subnets.json"
    cache.write_text(
        json.dumps(
            {
                "synced_at": "2026-09-25T00:00:00+00:00",
                "count": 1,
                "subnets": [{"netuid": 3, "name": "RegistryOnly"}],
            }
        )
    )
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert load_live_cache_rows() == []
