"""Hourly prune keeps one row per series per hour, disputed last (#1406 review item 3)."""

from __future__ import annotations

import sqlite3
import time

from internal.chain_price import config as cfg
from internal.chain_price import db as price_db

HOUR_MS = 3_600_000
DAY_MS = 86_400_000


def _row(netuid, provider, registered_at, series_key, block, ts_ms, quality="chain_sampled"):
    return {
        "netuid": netuid,
        "block": block,
        "provider": provider,
        "ts_ms": ts_ms,
        "registered_at": registered_at,
        "tao_reserve_raw": 1,
        "alpha_reserve_raw": 1,
        "price_tao": 1.0,
        "spot_price_tao": None,
        "unit": "tao",
        "quality": quality,
        "schema_version": cfg.SCHEMA_VERSION,
        "series_key": series_key,
    }


def test_downsample_keeps_one_row_per_series_hour_and_prefers_valid(tmp_path):
    # The downsample window is [age_cutoff, full_cutoff); the rows must land inside it.
    assert cfg.RETENTION_FULL_DAYS + 1 < cfg.RETENTION_DAYS
    db_path = str(tmp_path / "chain_prices.db")
    price_db.ensure_schema(db_path)

    # One hour bucket, well inside the downsample window and away from the hour edges.
    hour_start = (int(time.time() * 1000) - (cfg.RETENTION_FULL_DAYS + 1) * DAY_MS) // HOUR_MS * HOUR_MS
    base = hour_start + 1_000
    rows = [
        # netuid 1 / provider a / registration 1: disputed row is earlier than the valid row.
        _row(1, "a", 1, "s1", 10, base, quality="disputed"),
        _row(1, "a", 1, "s1", 11, base + 1_000),
        # netuid 1 / provider a / registration 2: two valid rows, same hour.
        _row(1, "a", 2, "s2", 20, base + 2_000),
        _row(1, "a", 2, "s2", 21, base + 3_000),
        # netuid 2 / provider b: its own series, must survive untouched.
        _row(2, "b", 1, "s3", 30, base + 4_000),
    ]
    assert price_db.insert_sample_rows(rows, path=db_path) == len(rows)

    conn = sqlite3.connect(db_path)
    before = conn.execute("SELECT COUNT(*) FROM chain_price_samples").fetchone()[0]
    conn.close()

    stats = price_db.run_hourly_prune_job(path=db_path)

    conn = sqlite3.connect(db_path)
    kept = sorted(
        r[0] for r in conn.execute("SELECT block FROM chain_price_samples").fetchall()
    )
    after = conn.execute("SELECT COUNT(*) FROM chain_price_samples").fetchone()[0]
    conn.close()

    # Exactly one row per (netuid, provider, series, hour): the valid earliest one.
    assert kept == [11, 20, 30]
    assert stats["deleted_samples"] == before - after == 2

    # Each registration still has a usable bar; the old hour-only partition removed one.
    bar_s1 = price_db.select_chain_bar(
        netuid=1,
        registered_at=1,
        series_key="s1",
        resolve_at_ms=base + 1_500,
        max_staleness_ms=60_000,
        path=db_path,
    )
    bar_s2 = price_db.select_chain_bar(
        netuid=1,
        registered_at=2,
        series_key="s2",
        resolve_at_ms=base + 2_500,
        max_staleness_ms=60_000,
        path=db_path,
    )
    assert bar_s1 is not None and bar_s1["block"] == 11
    assert bar_s2 is not None and bar_s2["block"] == 20
