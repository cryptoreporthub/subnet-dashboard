"""Startup cache coverage audit — worker gate + CACHE_COVERAGE_STRICT."""

from __future__ import annotations

import logging

import pytest

from internal.council.price_reference import (
    cache_coverage_strict_enabled,
    run_startup_cache_coverage_audit,
)


def _write_json(path, payload):
    import json

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def test_startup_audit_skips_when_no_predictions(tmp_path):
    report = run_startup_cache_coverage_audit(
        predictions_path=str(tmp_path / "missing.json"),
        cache_path=str(tmp_path / "cache.json"),
    )
    assert report["skipped"] is True


def test_startup_audit_ok_when_covered(tmp_path, caplog):
    preds = tmp_path / "predictions.json"
    cache = tmp_path / "price_cache.json"
    _write_json(
        preds,
        {
            "predictions": [{"netuid": 1}],
            "resolved": [],
            "stats": {},
        },
    )
    _write_json(
        cache,
        {"1": {"candles": [{"timestamp": "2026-01-01T00:00:00+00:00", "close": 1.0}]}},
    )
    with caplog.at_level(logging.INFO, logger="internal.council.price_reference"):
        report = run_startup_cache_coverage_audit(
            predictions_path=str(preds),
            cache_path=str(cache),
        )
    assert report["ok"] == ["1"]
    assert report["missing"] == []
    assert any("covered in price_cache" in m for m in caplog.messages)


def test_startup_audit_strict_aborts(tmp_path, monkeypatch):
    monkeypatch.setenv("CACHE_COVERAGE_STRICT", "true")
    assert cache_coverage_strict_enabled() is True

    preds = tmp_path / "predictions.json"
    cache = tmp_path / "price_cache.json"
    _write_json(preds, {"predictions": [{"netuid": 9}], "resolved": [], "stats": {}})
    _write_json(cache, {})

    with pytest.raises(RuntimeError, match="CACHE_COVERAGE_STRICT"):
        run_startup_cache_coverage_audit(
            predictions_path=str(preds),
            cache_path=str(cache),
        )


def test_startup_audit_non_strict_continues(tmp_path, caplog):
    preds = tmp_path / "predictions.json"
    cache = tmp_path / "price_cache.json"
    _write_json(preds, {"predictions": [{"netuid": 9}], "resolved": [], "stats": {}})
    _write_json(cache, {})

    with caplog.at_level(logging.WARNING, logger="internal.council.price_reference"):
        report = run_startup_cache_coverage_audit(
            predictions_path=str(preds),
            cache_path=str(cache),
        )
    assert report["missing"] == ["9"]
    assert any("missing cache keys" in m for m in caplog.messages)
