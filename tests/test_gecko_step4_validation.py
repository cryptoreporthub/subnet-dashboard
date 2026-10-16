"""Tests for #1395 Fix 5 Gecko Step 4 validation protocol."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from internal.chain_price.gecko_validation import (
    MatchedHour,
    SubnetValidationInput,
    evaluate_gecko_validation,
    subnet_metrics,
    subnets_from_serializable,
)
from scripts.gecko_step4_validation import _gecko_params, main

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "gecko_validation"


def _load(name: str) -> dict:
    with (FIXTURES / name).open(encoding="utf-8") as f:
        return json.load(f)


def test_gecko_params_currency_token_and_base():
    params = _gecko_params({"base_is_alpha": True}, 48)
    assert params["currency"] == "token"
    assert params["token"] == "base"
    assert params["limit"] == 48


def test_gecko_params_tao_base_uses_quote_token():
    params = _gecko_params({"base_is_alpha": False}, 24)
    assert params["token"] == "quote"


def test_subnet_metrics_log_return_correlation_high_when_aligned():
    matched = [
        MatchedHour(gecko_close=0.01 + i * 0.0001, chain_price_tao=(0.01 + i * 0.0001) * 1.00001)
        for i in range(30)
    ]
    m = subnet_metrics(matched)
    assert m["matched_hours"] == 30
    assert m["hourly_log_return_corr"] is not None
    assert m["hourly_log_return_corr"] > 0.99


def test_evaluate_pass_fixture():
    subnets = subnets_from_serializable(_load("synthetic_pass.json")["subnets"])
    report = evaluate_gecko_validation(subnets)
    assert report["verdict"] == "PASS"
    assert report["aggregate"]["qualifying_subnet_count"] == 8
    assert report["threshold_checks"]["median_rel_diff_le_max"] is True
    assert report["threshold_checks"]["p95_rel_diff_le_max"] is True
    assert report["threshold_checks"]["mean_hourly_log_return_corr_ge_min"] is True


def test_evaluate_fail_fixture():
    subnets = subnets_from_serializable(_load("synthetic_fail.json")["subnets"])
    report = evaluate_gecko_validation(subnets)
    assert report["verdict"] == "FAIL"
    assert report["aggregate"]["qualifying_subnet_count"] >= 8


def test_evaluate_inconclusive_sparse_11_subnets():
    """11 subnets with 0–10 matched hours each — none reach the 24h floor."""
    subnets = subnets_from_serializable(_load("synthetic_inconclusive_sparse.json")["subnets"])
    report = evaluate_gecko_validation(subnets)
    assert report["verdict"] == "INCONCLUSIVE"
    assert report["aggregate"]["qualifying_subnet_count"] == 0
    assert len(report["excluded_subnets"]) == 11


def test_evaluate_inconclusive_only_seven_qualifying():
    subnets = subnets_from_serializable(_load("synthetic_inconclusive_seven.json")["subnets"])
    report = evaluate_gecko_validation(subnets)
    assert report["verdict"] == "INCONCLUSIVE"
    assert report["aggregate"]["qualifying_subnet_count"] == 7


def test_script_writes_report_from_fixture(tmp_path: Path):
    out = tmp_path / "report.json"
    rc = main(
        [
            "--input",
            str(FIXTURES / "synthetic_pass.json"),
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    payload = json.loads(out.read_text())
    assert payload["protocol"] == "gecko_step4_validation"
    assert payload["currency"] == "token"
    assert payload["verdict"] == "PASS"
    assert payload["git_sha"]


def test_committed_sample_output_is_pass_verdict():
    sample = FIXTURES / "sample_protocol_output.json"
    assert sample.is_file()
    payload = json.loads(sample.read_text())
    assert payload["verdict"] == "PASS"
    assert payload["mode"] == "fixture"
