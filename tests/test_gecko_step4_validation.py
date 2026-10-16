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
from scripts import gecko_step4_validation as step4_script
from scripts.gecko_step4_validation import _gecko_params, _live_probe_subnets, main

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
    assert report["aggregate"]["qualifying_subnet_count"] == 0
    assert len(report["failing_subnets"]) == 8


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


def _aligned_matched(n: int = 30, base: float = 0.01) -> list[MatchedHour]:
    return [
        MatchedHour(gecko_close=base + i * 0.0001, chain_price_tao=(base + i * 0.0001) * 1.00001)
        for i in range(n)
    ]


def test_unit_mismatch_subnet_fails_even_with_large_pool():
    good = [SubnetValidationInput(netuid=i, matched=_aligned_matched()) for i in range(19)]
    bad = SubnetValidationInput(
        netuid=99,
        matched=[
            MatchedHour(gecko_close=0.006 + i * 0.0001, chain_price_tao=1.3 + i * 0.02)
            for i in range(30)
        ],
    )
    report = evaluate_gecko_validation(good + [bad])
    assert report["verdict"] == "FAIL"
    fail99 = next(f for f in report["failing_subnets"] if f["netuid"] == 99)
    assert "price_unit_mismatch" in fail99["reasons"]


def test_flat_series_excluded_undefined_return_corr():
    good = [SubnetValidationInput(netuid=i, matched=_aligned_matched()) for i in range(7)]
    flat = SubnetValidationInput(
        netuid=88,
        matched=[MatchedHour(gecko_close=0.01, chain_price_tao=0.01) for _ in range(30)],
    )
    report = evaluate_gecko_validation(good + [flat])
    assert report["verdict"] == "INCONCLUSIVE"
    assert report["aggregate"]["qualifying_subnet_count"] == 7
    assert any(
        e["netuid"] == 88 and e["reason"] == "undefined_return_corr"
        for e in report["excluded_subnets"]
    )


def test_flat_unit_mismatch_fails_before_undefined_corr_exclusion():
    """8 good + flat wrong-unit series must FAIL (also excluded as undefined_return_corr)."""
    good = [SubnetValidationInput(netuid=i, matched=_aligned_matched()) for i in range(8)]
    flat_bad = SubnetValidationInput(
        netuid=99,
        matched=[MatchedHour(gecko_close=0.01, chain_price_tao=10.0) for _ in range(30)],
    )
    report = evaluate_gecko_validation(good + [flat_bad])
    assert report["verdict"] == "FAIL"
    assert report["aggregate"]["qualifying_subnet_count"] == 8
    fail99 = next(f for f in report["failing_subnets"] if f["netuid"] == 99)
    assert "price_unit_mismatch" in fail99["reasons"]
    assert any(
        e["netuid"] == 99 and e["reason"] == "undefined_return_corr"
        for e in report["excluded_subnets"]
    )


def test_gecko_flat_chain_thousand_x_moving_fails():
    good = [SubnetValidationInput(netuid=i, matched=_aligned_matched()) for i in range(8)]
    bad = SubnetValidationInput(
        netuid=99,
        matched=[MatchedHour(gecko_close=0.01, chain_price_tao=10.0 + i * 0.1) for i in range(30)],
    )
    report = evaluate_gecko_validation(good + [bad])
    assert report["verdict"] == "FAIL"
    assert any(f["netuid"] == 99 for f in report["failing_subnets"])


def test_below_floor_unit_mismatch_inconclusive_not_pass():
    good = [SubnetValidationInput(netuid=i, matched=_aligned_matched()) for i in range(8)]
    short_bad = SubnetValidationInput(
        netuid=99,
        matched=[MatchedHour(gecko_close=0.01, chain_price_tao=10.0) for _ in range(20)],
    )
    report = evaluate_gecko_validation(good + [short_bad])
    assert report["verdict"] == "INCONCLUSIVE"
    assert report["unit_mismatch_below_floor"] == [{"netuid": 99, "matched_hours": 20}]
    assert any(
        e["netuid"] == 99 and e["reason"] == "below_floor_24h"
        for e in report["excluded_subnets"]
    )


def test_at_floor_unit_mismatch_fails_even_when_quorum_short():
    good = [SubnetValidationInput(netuid=i, matched=_aligned_matched()) for i in range(3)]
    bad = SubnetValidationInput(
        netuid=99,
        matched=[MatchedHour(gecko_close=0.01, chain_price_tao=10.0) for _ in range(30)],
    )
    report = evaluate_gecko_validation(good + [bad])
    assert report["verdict"] == "FAIL"
    assert report["aggregate"]["qualifying_subnet_count"] == 3


def test_matched_hours_boundary_24_qualifies_23_excluded():
    aligned = _aligned_matched(n=24)
    short = _aligned_matched(n=23)
    eight = [SubnetValidationInput(netuid=i, matched=aligned) for i in range(8)]
    report_ok = evaluate_gecko_validation(eight)
    assert report_ok["verdict"] == "PASS"
    assert report_ok["aggregate"]["qualifying_subnet_count"] == 8
    nine = eight + [SubnetValidationInput(netuid=99, matched=short)]
    report_short = evaluate_gecko_validation(nine)
    assert report_short["aggregate"]["qualifying_subnet_count"] == 8
    assert any(
        e["netuid"] == 99 and e["reason"] == "below_floor_24h"
        for e in report_short["excluded_subnets"]
    )


def test_qualifying_subnet_boundary_eight_pass_seven_inconclusive():
    aligned = _aligned_matched()
    seven = [SubnetValidationInput(netuid=i, matched=aligned) for i in range(7)]
    report7 = evaluate_gecko_validation(seven)
    assert report7["verdict"] == "INCONCLUSIVE"
    assert report7["aggregate"]["qualifying_subnet_count"] == 7
    eight = [SubnetValidationInput(netuid=i, matched=aligned) for i in range(8)]
    report8 = evaluate_gecko_validation(eight)
    assert report8["verdict"] == "PASS"
    assert report8["aggregate"]["qualifying_subnet_count"] == 8


def test_live_probe_uses_close_timestamp_and_skips_in_progress(monkeypatch):
    now_ts = 1_700_000_000
    monkeypatch.setattr(step4_script.time, "time", lambda: float(now_ts))
    recorded: list[int] = []

    def fake_resolve(_reader, target_ms, search="bracketed"):
        recorded.append(target_ms)
        return (1, "0xabc", "ok")

    def fake_reserve(_reader, _netuid, _block_hash):
        return 0.01

    monkeypatch.setattr(step4_script, "resolve_block_at", fake_resolve)
    monkeypatch.setattr(step4_script, "_reserve_price_tao", fake_reserve)
    monkeypatch.setattr(
        step4_script,
        "_fetch_gecko_ohlcv",
        lambda *_a, **_k: [
            [now_ts, 0, 0, 0, 1.0],
            [now_ts - 7200, 0, 0, 0, 0.99],
            [now_ts - 3600, 0, 0, 0, 0.995],
        ],
    )

    class _Reader:
        pass

    mapped = [(64, "bittensor", "pool", {"base_is_alpha": True})]
    subs = _live_probe_subnets(mapped, window_hours=48, reader=_Reader())
    assert len(subs) == 1
    assert len(subs[0].matched) == 2
    assert recorded == [(now_ts - 3600) * 1000, now_ts * 1000]


SAMPLE_REPORT_TOP_KEYS = frozenset(
    {
        "protocol",
        "version",
        "git_sha",
        "generated_at",
        "mode",
        "window_hours",
        "currency",
        "verdict",
        "parameters",
        "aggregate",
        "threshold_checks",
        "excluded_subnets",
        "failing_subnets",
        "unit_mismatch_below_floor",
        "per_subnet",
    }
)

SAMPLE_PER_SUBNET_KEYS = frozenset(
    {
        "netuid",
        "pool",
        "matched_hours",
        "median_rel_diff",
        "p95_rel_diff",
        "hourly_log_return_corr",
        "price_unit_mismatch",
    }
)


def test_committed_sample_output_is_pass_verdict():
    sample = FIXTURES / "sample_protocol_output.json"
    assert sample.is_file()
    payload = json.loads(sample.read_text())
    assert SAMPLE_REPORT_TOP_KEYS <= frozenset(payload)
    assert payload["protocol"] == "gecko_step4_validation"
    assert payload["verdict"] == "PASS"
    assert payload["mode"] == "fixture"
    assert payload["currency"] == "token"
    assert payload["aggregate"]["qualifying_subnet_count"] >= 8
    assert payload["threshold_checks"]["per_subnet_median_and_unit"] is True
    assert payload["failing_subnets"] == []
    assert payload["unit_mismatch_below_floor"] == []
    assert payload["excluded_subnets"] == []
    for row in payload["per_subnet"]:
        assert SAMPLE_PER_SUBNET_KEYS <= frozenset(row)
        assert row["price_unit_mismatch"] is False
