"""Soul weights chip helper tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

from internal.analytics.soul_weights_chip import soul_weights_chip_context

_NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)


def test_chip_when_recent(tmp_path):
    path = tmp_path / "soul_map.json"
    path.write_text(
        json.dumps({"soul_map_state": {"updated_at": "2026-07-23T12:00:00Z"}}),
        encoding="utf-8",
    )

    with patch("internal.analytics.soul_weights_chip.datetime") as mock_dt:
        mock_dt.now.return_value = _NOW
        mock_dt.fromisoformat = datetime.fromisoformat
        out = soul_weights_chip_context(soul_map_path=str(path), max_age_days=7)
    assert out["soul_weights_chip"]["ago"] == "1d ago"


def test_chip_honest_empty_when_stale(tmp_path):
    path = tmp_path / "soul_map.json"
    path.write_text(
        json.dumps({"soul_map_state": {"updated_at": "2026-01-01T00:00:00Z"}}),
        encoding="utf-8",
    )

    with patch("internal.analytics.soul_weights_chip.datetime") as mock_dt:
        mock_dt.now.return_value = _NOW
        mock_dt.fromisoformat = datetime.fromisoformat
        assert soul_weights_chip_context(soul_map_path=str(path))["soul_weights_chip"] is None
