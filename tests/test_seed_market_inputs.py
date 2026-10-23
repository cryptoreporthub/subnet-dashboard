"""Authoritative seed market inputs (#1484 P1)."""

from __future__ import annotations

from internal.council.build_seed_snapshot import build_image_seed_snapshot
from internal.council.seed_market_inputs import build_authoritative_hydrate_rows
from internal.council.seed_quality import validate_shipped_seed
import json
import tempfile


def test_authoritative_rows_use_registry_names_not_alpha_pattern():
    rows, prov = build_authoritative_hydrate_rows()
    assert len(rows) == 128
    assert prov["hydrate_row_count"] == 128
    for row in rows[:5]:
        name = row["name"]
        assert "Alpha Subnet" not in name
        assert row["price"] > 0


def test_build_128_seed_passes_validate_shipped_seed():
    with tempfile.TemporaryDirectory() as tmp:
        volume = f"{tmp}/vol.json"
        cycle = f"{tmp}/cycle.json"
        out = build_image_seed_snapshot(volume_path=volume, cycle_path=cycle)
        assert out.get("published")
        snap = json.loads(open(volume, encoding="utf-8").read())
        ok, reason = validate_shipped_seed(snap)
        assert ok, reason
        assert snap["build_provenance"]["market_inputs"]["universe_sha256"]
