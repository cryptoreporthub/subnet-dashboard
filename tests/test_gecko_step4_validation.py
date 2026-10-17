"""Tests for #1395 Fix 5 Gecko Step 4 validation protocol."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from internal.chain_price.gecko_validation import (
    ALIGNED_HOUR_SECONDS,
    MatchedHour,
    SubnetValidationInput,
    _hourly_log_returns_scaled,
    _pearson,
    evaluate_gecko_validation,
    subnet_metrics,
    subnets_from_serializable,
)
from scripts import gecko_step4_validation as step4_script
from internal.chain_price.storage_keys import map_key_hex
from scripts.gecko_step4_validation import (
    _gecko_fetch_error_label,
    _gecko_params,
    _live_probe_subnets,
    _reserve_price_tao_with_outcome,
    main,
)

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
        return 0.01, "ok"

    monkeypatch.setattr(step4_script, "resolve_block_at", fake_resolve)
    monkeypatch.setattr(step4_script, "_reserve_price_tao_with_outcome", fake_reserve)
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
        provider_served = None
        fallback_count = 0
        rate_limit_events = []

        def reset_probe_diagnostics(self):
            pass

    mapped = [(64, "bittensor", "pool", {"base_is_alpha": True})]
    subs, probe_meta = _live_probe_subnets(mapped, window_hours=48, reader=_Reader())
    assert len(subs) == 1
    assert len(subs[0].matched) == 2
    assert "per_subnet" in probe_meta
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
        "warnings",
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
        "n_return_pairs",
        "return_pair_dt_over_3600_count",
        "return_pair_dt_max_seconds",
        "matched_hour_span_hours",
        "return_pair_dt_exact_3600_count",
        "duplicate_hour_unix_dropped",
        "coverage",
        "data_integrity_error",
        "median_rel_diff",
        "p95_rel_diff",
        "hourly_log_return_corr",
        "corr_below_warn_threshold",
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
        span_h = row["matched_hour_span_hours"]
        mh = row["matched_hours"]
        expected_cov = mh / (span_h + 1.0) if mh > 0 else 0.0
        assert row["coverage"] == pytest.approx(expected_cov, rel=1e-9)


def _five_minute_stamped_matched(n: int = 24, base_ts: int = 1_700_000_000) -> list[MatchedHour]:
    """Replit #1431 post-merge: 24 rows every 5m must not satisfy the 24h floor."""
    step = 300
    return [
        MatchedHour(
            gecko_close=0.01 + i * 0.0001,
            chain_price_tao=(0.01 + i * 0.0001) * 1.00001,
            hour_unix=base_ts + i * step,
        )
        for i in range(n)
    ]


def test_sub_hourly_cadence_cannot_pass_hour_floor():
    matched = _five_minute_stamped_matched(24)
    metrics = subnet_metrics(matched)
    assert metrics["matched_hours"] == 24
    assert metrics["matched_hour_span_hours"] == pytest.approx(23 * 300 / ALIGNED_HOUR_SECONDS)
    assert metrics["matched_hours"] / (metrics["matched_hour_span_hours"] + 1) > 1.0
    eight = [SubnetValidationInput(netuid=i, matched=matched) for i in range(8)]
    report = evaluate_gecko_validation(eight)
    assert report["verdict"] == "INCONCLUSIVE"
    assert report["aggregate"]["qualifying_subnet_count"] == 0
    assert all(
        e["reason"] == "sub_hourly_cadence" for e in report["excluded_subnets"]
    )


def _good_subnets(n: int, start: int = 0) -> list[SubnetValidationInput]:
    return [SubnetValidationInput(netuid=start + i, matched=_aligned_matched()) for i in range(n)]


def _flat(netuid: int, gecko: float, chain: float, n: int = 30) -> SubnetValidationInput:
    return SubnetValidationInput(
        netuid=netuid,
        matched=[MatchedHour(gecko_close=gecko, chain_price_tao=chain) for _ in range(n)],
    )


def _scaled(netuid: int, factor: float, n: int = 30) -> SubnetValidationInput:
    return SubnetValidationInput(
        netuid=netuid,
        matched=[
            MatchedHour(gecko_close=m.gecko_close, chain_price_tao=m.chain_price_tao * factor)
            for m in _aligned_matched(n)
        ],
    )


def test_flat_series_with_large_median_error_fails_not_silently_excluded():
    report = evaluate_gecko_validation(_good_subnets(8) + [_flat(99, 0.010, 0.015)])
    assert report["verdict"] == "FAIL"
    fail99 = next(f for f in report["failing_subnets"] if f["netuid"] == 99)
    assert fail99["reasons"] == ["median_rel_diff_exceeds_max"]
    assert any(
        e["netuid"] == 99 and e["reason"] == "undefined_return_corr"
        for e in report["excluded_subnets"]
    )


def test_gecko_flat_chain_moving_three_percent_off_fails():
    bad = SubnetValidationInput(
        netuid=99,
        matched=[
            MatchedHour(gecko_close=0.07, chain_price_tao=0.07 * 1.03 * (1 + i * 0.0001))
            for i in range(30)
        ],
    )
    report = evaluate_gecko_validation(_good_subnets(8) + [bad])
    assert report["verdict"] == "FAIL"
    assert any(f["netuid"] == 99 for f in report["failing_subnets"])


def test_flat_series_with_agreeing_prices_is_excluded_but_does_not_fail():
    report = evaluate_gecko_validation(_good_subnets(8) + [_flat(99, 0.07, 0.07)])
    assert report["verdict"] == "PASS"
    assert report["failing_subnets"] == []
    assert any(
        e["netuid"] == 99 and e["reason"] == "undefined_return_corr"
        for e in report["excluded_subnets"]
    )


def test_below_floor_unit_mismatch_does_not_mask_a_definite_fail():
    subnets = _good_subnets(8) + [_scaled(90, 1.03), _flat(91, 0.01, 10.0, n=20)]
    report = evaluate_gecko_validation(subnets)
    assert report["verdict"] == "FAIL"
    assert [f["netuid"] for f in report["failing_subnets"]] == [90]
    assert report["unit_mismatch_below_floor"] == [{"netuid": 91, "matched_hours": 20}]


def test_flat_median_failure_counts_toward_fail_quorum_but_too_few_stays_inconclusive():
    seven = evaluate_gecko_validation(_good_subnets(7) + [_flat(99, 0.010, 0.015)])
    assert seven["verdict"] == "FAIL"  # 7 qualifying + 1 evaluated failure = 8 evaluated
    five = evaluate_gecko_validation(_good_subnets(5) + [_flat(99, 0.010, 0.015)])
    assert five["verdict"] == "INCONCLUSIVE"  # only 6 evaluated


def test_pooled_p95_nearest_rank_fails_when_five_percent_exceed_limit():
    """192 pooled points: int(0.95*n)-1 false-PASSes; ceil(0.95*n)-1 must FAIL."""
    good = [
        SubnetValidationInput(netuid=i, matched=_aligned_matched(24))
        for i in range(7)
    ]
    mixed_hours: list[MatchedHour] = []
    for i in range(24):
        g = 0.01 + i * 0.0001
        factor = 1.0001 if i < 14 else 1.04
        mixed_hours.append(MatchedHour(gecko_close=g, chain_price_tao=g * factor))
    mixed = SubnetValidationInput(netuid=99, matched=mixed_hours)
    report = evaluate_gecko_validation(good + [mixed])
    assert report["aggregate"]["n_price_points"] == 192
    assert report["aggregate"]["p95_rel_diff"] == pytest.approx(0.04, rel=1e-6)
    assert report["threshold_checks"]["p95_rel_diff_le_max"] is False
    assert report["verdict"] == "FAIL"


def _low_corr_matched(n: int = 30, base: float = 0.01) -> list[MatchedHour]:
    """Orthogonal wiggles: tight rel_diff, hourly log-return corr well below 0.7."""
    return [
        MatchedHour(
            gecko_close=base + 0.00005 * math.sin(i * 0.7),
            chain_price_tao=(base + 0.00005 * math.cos(i * 1.9)) * 1.00001,
        )
        for i in range(n)
    ]


def test_low_per_subnet_corr_warns_without_failing_verdict():
    """Low corr subnet warns only; cohort mean may still PASS when enough peers are tight."""
    good = [SubnetValidationInput(netuid=i, matched=_aligned_matched()) for i in range(19)]
    bad = SubnetValidationInput(netuid=99, matched=_low_corr_matched())
    report = evaluate_gecko_validation(good + [bad])
    assert report["verdict"] == "PASS"
    assert report["aggregate"]["qualifying_subnet_count"] == 20
    row99 = next(r for r in report["per_subnet"] if r["netuid"] == 99)
    assert row99["corr_below_warn_threshold"] is True
    assert any(w["netuid"] == 99 for w in report["warnings"])
    assert report["failing_subnets"] == []
    assert (
        report["parameters"]["thresholds"]["per_subnet_hourly_log_return_corr_warn_min"] == 0.7
    )


def test_per_subnet_corr_warn_false_when_all_meet_warn_min():
    report = evaluate_gecko_validation(_good_subnets(8))
    assert report["verdict"] == "PASS"
    assert report["warnings"] == []
    for row in report["per_subnet"]:
        assert row["corr_below_warn_threshold"] is False


def test_gapped_timestamps_scale_returns_not_naive_pairing():
    """A 2h gap must halve the per-hour rate; naive adjacent pairing would overstate it."""
    base_ts = 1_700_000_000
    matched = [
        MatchedHour(100.0, 100.0, hour_unix=base_ts),
        MatchedHour(121.0, 118.0, hour_unix=base_ts + 2 * ALIGNED_HOUR_SECONDS),
        MatchedHour(133.1, 130.0, hour_unix=base_ts + 3 * ALIGNED_HOUR_SECONDS),
        MatchedHour(140.0, 136.0, hour_unix=base_ts + 4 * ALIGNED_HOUR_SECONDS),
    ]
    closes_g = [m.gecko_close for m in matched]
    closes_c = [m.chain_price_tao for m in matched]
    stamps = [int(m.hour_unix) for m in matched]
    scaled_g = _hourly_log_returns_scaled(closes_g, stamps)
    naive_g = [math.log(closes_g[i] / closes_g[i - 1]) for i in range(1, len(closes_g))]
    assert scaled_g != naive_g
    assert scaled_g[0] == pytest.approx(math.log(121 / 100) * 0.5, rel=1e-9)
    scaled_c = _hourly_log_returns_scaled(closes_c, stamps)
    naive_c = [math.log(closes_c[i] / closes_c[i - 1]) for i in range(1, len(closes_c))]
    assert _pearson(scaled_g, scaled_c) != _pearson(naive_g, naive_c)
    metrics = subnet_metrics(matched)
    assert metrics["hourly_log_return_corr"] == _pearson(scaled_g, scaled_c)
    assert metrics["return_pair_dt_over_3600_count"] == 1
    assert metrics["return_pair_dt_max_seconds"] == 2 * ALIGNED_HOUR_SECONDS
    assert metrics["return_pair_dt_exact_3600_count"] == 2
    assert metrics["matched_hour_span_hours"] == pytest.approx(4.0)


def test_subnet_metrics_gap_diagnostics_on_aligned_series():
    matched = _stamped_aligned_matched(24)
    metrics = subnet_metrics(matched)
    assert metrics["return_pair_dt_over_3600_count"] == 0
    assert metrics["return_pair_dt_max_seconds"] == ALIGNED_HOUR_SECONDS
    assert metrics["return_pair_dt_exact_3600_count"] == 23
    assert metrics["matched_hour_span_hours"] == pytest.approx(23.0)


def test_subnet_metrics_sorts_unsorted_timestamps_before_returns():
    """Unsorted input must not pair adjacent list rows (review repro)."""
    base_ts = 1_700_000_000
    chronological = [
        MatchedHour(100.0, 100.0, hour_unix=base_ts),
        MatchedHour(121.0, 118.0, hour_unix=base_ts + 2 * ALIGNED_HOUR_SECONDS),
        MatchedHour(133.1, 130.0, hour_unix=base_ts + 3 * ALIGNED_HOUR_SECONDS),
        MatchedHour(140.0, 136.0, hour_unix=base_ts + 4 * ALIGNED_HOUR_SECONDS),
    ]
    shuffled = list(reversed(chronological))
    assert subnet_metrics(shuffled)["hourly_log_return_corr"] == subnet_metrics(chronological)[
        "hourly_log_return_corr"
    ]


def test_subnet_metrics_dedupes_hour_unix_keeps_last():
    base_ts = 1_700_000_000
    rows = [
        MatchedHour(10.0, 10.0, hour_unix=base_ts),
        MatchedHour(20.0, 20.0, hour_unix=base_ts + ALIGNED_HOUR_SECONDS),
        MatchedHour(10.0, 10.0, hour_unix=base_ts),  # duplicate ts, same prices — last wins
        MatchedHour(30.0, 30.0, hour_unix=base_ts + 2 * ALIGNED_HOUR_SECONDS),
        MatchedHour(40.0, 40.0, hour_unix=base_ts + 3 * ALIGNED_HOUR_SECONDS),
        MatchedHour(50.0, 50.0, hour_unix=base_ts + 4 * ALIGNED_HOUR_SECONDS),
    ]
    metrics = subnet_metrics(rows)
    assert metrics["duplicate_hour_unix_dropped"] == 1
    assert metrics["matched_hours"] == 5
    assert metrics["n_return_pairs"] == 4


def test_duplicate_hour_unix_deduped_below_hour_floor():
    """Raw row count must not bypass the floor when duplicates collapse hours."""
    ts = 1_700_000_000
    single_ts = [
        MatchedHour(gecko_close=0.01, chain_price_tao=0.01, hour_unix=ts) for _ in range(24)
    ]
    report = evaluate_gecko_validation(
        _good_subnets(8) + [SubnetValidationInput(netuid=77, matched=single_ts)]
    )
    assert report["aggregate"]["qualifying_subnet_count"] == 8
    assert any(
        e["netuid"] == 77 and e["reason"] == "below_floor_24h"
        for e in report["excluded_subnets"]
    )
    row77 = next(r for r in report["per_subnet"] if r["netuid"] == 77)
    assert row77["matched_hours"] == 1
    assert row77["duplicate_hour_unix_dropped"] == 23


def test_mixed_hour_unix_excluded_fail_closed():
    """Stamped + unstamped rows must not combine synthetic and epoch times."""
    base = 1_700_000_000
    stamped = [
        MatchedHour(0.01 + i * 0.0001, 0.01 + i * 0.0001, hour_unix=base + i * ALIGNED_HOUR_SECONDS)
        for i in range(5)
    ]
    tail = [MatchedHour(0.015, 0.015)]
    report = evaluate_gecko_validation(
        [SubnetValidationInput(netuid=1, matched=stamped + tail)],
        min_matched_hours=6,
        min_qualifying_subnets=1,
    )
    row = report["per_subnet"][0]
    assert row["data_integrity_error"] == "mixed_hour_unix"
    assert row["matched_hours"] == 0
    assert any(
        e["netuid"] == 1 and e["reason"] == "mixed_hour_unix"
        for e in report["excluded_subnets"]
    )


def _stamped_aligned_matched(n: int = 30, base_ts: int = 1_700_000_000) -> list[MatchedHour]:
    return [
        MatchedHour(
            gecko_close=0.01 + i * 0.0001,
            chain_price_tao=(0.01 + i * 0.0001) * 1.00001,
            hour_unix=base_ts + i * ALIGNED_HOUR_SECONDS,
        )
        for i in range(n)
    ]


def test_mixed_hour_unix_among_stamped_blocks_pass_verdict():
    """Review repro (Grok 6217424854): 7 good + 8th with one missing stamp must not PASS."""
    good = [SubnetValidationInput(netuid=i, matched=_aligned_matched()) for i in range(7)]
    stamped = _stamped_aligned_matched(30)
    stamped[12] = MatchedHour(
        gecko_close=stamped[12].gecko_close,
        chain_price_tao=stamped[12].chain_price_tao,
        hour_unix=None,
    )
    bad = SubnetValidationInput(netuid=88, matched=stamped)
    report = evaluate_gecko_validation(good + [bad])
    assert report["verdict"] == "FAIL"
    assert report["aggregate"]["qualifying_subnet_count"] == 7
    fail88 = next(f for f in report["failing_subnets"] if f["netuid"] == 88)
    assert fail88["reasons"] == ["data_integrity_error:mixed_hour_unix"]
    row88 = next(r for r in report["per_subnet"] if r["netuid"] == 88)
    assert row88["data_integrity_error"] == "mixed_hour_unix"
    assert any(
        e["netuid"] == 88 and e["reason"] == "mixed_hour_unix"
        for e in report["excluded_subnets"]
    )


def test_conflicting_duplicate_hour_unix_data_integrity():
    base_ts = 1_700_000_000
    rows = [
        MatchedHour(10.0, 10.0, hour_unix=base_ts),
        MatchedHour(20.0, 20.0, hour_unix=base_ts + ALIGNED_HOUR_SECONDS),
        MatchedHour(99.0, 99.0, hour_unix=base_ts),
    ]
    metrics = subnet_metrics(rows)
    assert metrics["data_integrity_error"] == "conflicting_duplicate_hour_unix"
    report = evaluate_gecko_validation([SubnetValidationInput(netuid=1, matched=rows)])
    assert report["verdict"] == "INCONCLUSIVE"
    assert any(
        e["netuid"] == 1 and e["reason"] == "conflicting_duplicate_hour_unix"
        for e in report["excluded_subnets"]
    )


def _conflicting_duplicate_stamped_30h(base_ts: int = 1_700_000_000) -> list[MatchedHour]:
    """30 stamped hours with one conflicting duplicate at base_ts."""
    rows = _stamped_aligned_matched(30, base_ts=base_ts)
    rows.append(
        MatchedHour(
            gecko_close=99.0,
            chain_price_tao=99.0,
            hour_unix=base_ts + 5 * ALIGNED_HOUR_SECONDS,
        )
    )
    return rows


def _sparse_span_matched(
    n_rows: int = 24,
    span_hours: float = 60.0,
    base_ts: int = 1_700_000_000,
) -> list[MatchedHour]:
    """Stamped rows from first to last timestamp spanning span_hours."""
    span_seconds = int(span_hours * ALIGNED_HOUR_SECONDS)
    rows: list[MatchedHour] = []
    for i in range(n_rows):
        ts = base_ts + int(i * span_seconds / (n_rows - 1))
        g = 0.01 + i * 0.0001
        rows.append(MatchedHour(gecko_close=g, chain_price_tao=g * 1.00001, hour_unix=ts))
    return rows


def test_insufficient_coverage_excludes_sparse_24_over_60h_span():
    matched = _sparse_span_matched(24, 60.0)
    metrics = subnet_metrics(matched)
    assert metrics["matched_hours"] == 24
    assert metrics["matched_hour_span_hours"] == pytest.approx(60.0)
    assert metrics["matched_hours"] / (metrics["matched_hour_span_hours"] + 1) == pytest.approx(
        24 / 61, rel=1e-6
    )
    report = evaluate_gecko_validation([SubnetValidationInput(netuid=1, matched=matched)])
    assert report["verdict"] == "INCONCLUSIVE"
    assert report["aggregate"]["qualifying_subnet_count"] == 0
    assert any(
        e["netuid"] == 1 and e["reason"] == "insufficient_coverage"
        for e in report["excluded_subnets"]
    )
    assert report["failing_subnets"] == []


def test_healthy_coverage_still_qualifies():
    matched = _stamped_aligned_matched(24)
    metrics = subnet_metrics(matched)
    assert metrics["matched_hours"] / (metrics["matched_hour_span_hours"] + 1) > 0.5
    report = evaluate_gecko_validation(_good_subnets(8))
    assert report["verdict"] == "PASS"
    assert report["aggregate"]["qualifying_subnet_count"] == 8


def test_sparse_insufficient_coverage_unit_mismatch_not_pass():
    """Grok MODIFY 6222726055: coverage exclusion must not hide price_unit_mismatch."""
    good = [
        SubnetValidationInput(netuid=i, matched=_stamped_aligned_matched(24))
        for i in range(8)
    ]
    sparse_rows = _sparse_span_matched(24, 60.0)
    sparse_bad = SubnetValidationInput(
        netuid=99,
        matched=[
            MatchedHour(
                gecko_close=row.gecko_close,
                chain_price_tao=10.0 + i * 0.1,
                hour_unix=row.hour_unix,
            )
            for i, row in enumerate(sparse_rows)
        ],
    )
    report = evaluate_gecko_validation(good + [sparse_bad])
    assert report["verdict"] == "INCONCLUSIVE"
    assert report["unit_mismatch_below_floor"] == [{"netuid": 99, "matched_hours": 24}]
    assert any(
        e["netuid"] == 99 and e["reason"] == "insufficient_coverage"
        for e in report["excluded_subnets"]
    )


def test_insufficient_coverage_loses_quorum_inconclusive():
    good = [
        SubnetValidationInput(netuid=i, matched=_stamped_aligned_matched(24))
        for i in range(7)
    ]
    sparse = SubnetValidationInput(netuid=88, matched=_sparse_span_matched(24, 60.0))
    report = evaluate_gecko_validation(good + [sparse])
    assert report["verdict"] == "INCONCLUSIVE"
    assert report["aggregate"]["qualifying_subnet_count"] == 7
    assert any(
        e["netuid"] == 88 and e["reason"] == "insufficient_coverage"
        for e in report["excluded_subnets"]
    )


def test_live_probe_records_resolve_failures(monkeypatch):
    now_ts = 1_700_000_000
    monkeypatch.setattr(step4_script.time, "time", lambda: float(now_ts))
    outcomes = iter(["rate_limited", "archive_miss"])

    def fake_resolve(_reader, target_ms, search="bracketed"):
        outcome = next(outcomes)
        return None, None, outcome

    monkeypatch.setattr(step4_script, "resolve_block_at", fake_resolve)
    monkeypatch.setattr(
        step4_script,
        "_fetch_gecko_ohlcv",
        lambda *_a, **_k: [[now_ts - 3600, 0, 0, 0, 1.0], [now_ts - 7200, 0, 0, 0, 0.99]],
    )

    class _Reader:
        provider_served = "finney"
        fallback_count = 2
        rate_limit_events = [{"provider": "finney", "http_status": 429}]

        def reset_probe_diagnostics(self):
            pass

    mapped = [(64, "bittensor", "pool", {"base_is_alpha": True})]
    subs, meta = _live_probe_subnets(mapped, window_hours=48, reader=_Reader())
    assert len(subs[0].matched) == 0
    counts = meta["aggregate_stage_outcome_counts"]
    assert counts.get("resolve_block_at:rate_limited") == 1
    assert counts.get("resolve_block_at:archive_miss") == 1
    assert meta["provider_fallback_count"] == 2
    assert meta["rate_limit_events"][0]["http_status"] == 429
    report = evaluate_gecko_validation(subs)
    assert report["verdict"] != "PASS"


def test_live_probe_records_reserve_read_failures(monkeypatch):
    now_ts = 1_700_000_000
    monkeypatch.setattr(step4_script.time, "time", lambda: float(now_ts))

    def fake_resolve(_reader, target_ms, search="bracketed"):
        return 1, "0xabc", "ok"

    def fake_reserve(_reader, _netuid, _block_hash):
        return None, "missing_storage"

    monkeypatch.setattr(step4_script, "resolve_block_at", fake_resolve)
    monkeypatch.setattr(step4_script, "_reserve_price_tao_with_outcome", fake_reserve)
    monkeypatch.setattr(
        step4_script,
        "_fetch_gecko_ohlcv",
        lambda *_a, **_k: [[now_ts - 3600, 0, 0, 0, 1.0], [now_ts - 7200, 0, 0, 0, 0.99]],
    )

    class _Reader:
        provider_served = "blockmachine"
        fallback_count = 0
        rate_limit_events = []

        def reset_probe_diagnostics(self):
            pass

    subs, meta = _live_probe_subnets(
        [(64, "bittensor", "pool", {"base_is_alpha": True})],
        window_hours=48,
        reader=_Reader(),
    )
    counts = meta["aggregate_stage_outcome_counts"]
    assert counts.get("reserve_read:missing_storage") == 2
    assert evaluate_gecko_validation(subs)["verdict"] != "PASS"


def test_reserve_price_malformed_changes_short_row():
    keys = [map_key_hex(b"SubnetTAO", 64), map_key_hex(b"SubnetAlphaIn", 64)]

    class _Reader:
        def call(self, method, params):
            assert method == "state_queryStorageAt"
            return [{"changes": [[keys[0]]]}], "ok"

    price, outcome = _reserve_price_tao_with_outcome(_Reader(), 64, "0xabc")
    assert price is None
    assert outcome == "malformed_row"


@pytest.mark.parametrize(
    "bad_row",
    [[["0xdeadbeef"], "0x0a"], [map_key_hex(b"SubnetTAO", 64), 10]],
    ids=["unhashable_key", "non_str_value"],
)
def test_reserve_price_malformed_changes_bad_types(bad_row):
    class _Reader:
        def call(self, method, params):
            return [{"changes": [bad_row]}], "ok"

    price, outcome = _reserve_price_tao_with_outcome(_Reader(), 64, "0xabc")
    assert price is None
    assert outcome == "malformed_row"


@pytest.mark.parametrize(
    "bad_row",
    [
        [[map_key_hex(b"SubnetTAO", 64), "0x0a"], [map_key_hex(b"SubnetTAO", 64), "0x14"]],
        [[map_key_hex(b"SubnetTAO", 64), "0x0a"], [map_key_hex(b"SubnetTAO", 64), "0x0a"]],
    ],
    ids=["conflicting_duplicate", "identical_duplicate"],
)
def test_reserve_price_duplicate_keys_fail_closed(bad_row):
    class _Reader:
        def call(self, method, params):
            return [{"changes": bad_row}], "ok"

    price, outcome = _reserve_price_tao_with_outcome(_Reader(), 64, "0xabc")
    assert price is None
    assert outcome == "malformed_row"


def test_reserve_price_uppercase_keys_accepted():
    k_tao = map_key_hex(b"SubnetTAO", 64).upper()
    k_alpha = map_key_hex(b"SubnetAlphaIn", 64).upper()

    class _Reader:
        def call(self, method, params):
            return [{"changes": [[k_tao, "0x0a"], [k_alpha, "0x0a"]]}], "ok"

    price, outcome = _reserve_price_tao_with_outcome(_Reader(), 64, "0xabc")
    assert outcome == "ok"
    assert price == 1.0


def test_reserve_price_case_variant_conflicting_duplicate_malformed():
    k_tao = map_key_hex(b"SubnetTAO", 64)
    k_alpha = map_key_hex(b"SubnetAlphaIn", 64)
    changes = [
        [k_tao, "0x0a"],
        [k_tao.upper(), "0x14"],
        [k_alpha, "0x0a"],
    ]

    class _Reader:
        def call(self, method, params):
            return [{"changes": changes}], "ok"

    price, outcome = _reserve_price_tao_with_outcome(_Reader(), 64, "0xabc")
    assert price is None
    assert outcome == "malformed_row"


def test_reserve_price_unrequested_key_malformed():
    k_tao = map_key_hex(b"SubnetTAO", 64)
    k_alpha = map_key_hex(b"SubnetAlphaIn", 64)
    changes = [
        [k_tao, "0x0a"],
        [k_alpha, "0x0a"],
        ["0xdeadbeef", "0x01"],
    ]

    class _Reader:
        def call(self, method, params):
            return [{"changes": changes}], "ok"

    price, outcome = _reserve_price_tao_with_outcome(_Reader(), 64, "0xabc")
    assert price is None
    assert outcome == "malformed_row"


@pytest.mark.parametrize(
    "batch, expected",
    [
        ([{"changes": {}}], "malformed_row"),
        ([{"changes": [[]]}], "malformed_row"),
        ([{"changes": [None]}], "malformed_row"),
        ([{"changes": [["0xkey"]]}], "malformed_row"),
        ([{"changes": [["0xkey", "0x0a", "extra"]]}], "malformed_row"),
        ([None], "malformed_row"),
        ({}, "malformed_row"),
        ([{"changes": []}], "missing_storage"),
        ([{"changes": None}], "missing_storage"),
        ([{}], "missing_storage"),
        ([], "missing_storage"),
    ],
    ids=[
        "changes_dict",
        "empty_row",
        "none_row",
        "one_element_row",
        "three_element_row",
        "entry_not_dict",
        "batch_dict",
        "changes_empty_list",
        "changes_none",
        "entry_without_changes",
        "batch_empty",
    ],
)
def test_reserve_price_container_and_row_shapes(batch, expected):
    class _Reader:
        def call(self, method, params):
            return batch, "ok"

    price, outcome = _reserve_price_tao_with_outcome(_Reader(), 64, "0xabc")
    assert price is None
    assert outcome == expected


@pytest.mark.parametrize("bad_changes", [{}, [[]]], ids=["changes_dict", "empty_row"])
def test_live_probe_empty_malformed_reserve_container_counts_malformed(monkeypatch, bad_changes):
    now_ts = 1_700_000_000
    monkeypatch.setattr(step4_script.time, "time", lambda: float(now_ts))
    monkeypatch.setattr(step4_script, "resolve_block_at", lambda *_a, **_k: (1, "0xabc", "ok"))
    monkeypatch.setattr(
        step4_script,
        "_fetch_gecko_ohlcv",
        lambda *_a, **_k: [[now_ts - 3600, 0, 0, 0, 0.01]],
    )

    def _good_changes(netuid: int) -> list:
        k_tao = map_key_hex(b"SubnetTAO", netuid)
        k_alpha = map_key_hex(b"SubnetAlphaIn", netuid)
        return [[k_tao, "0x0a"], [k_alpha, "0x0a"]]

    class _Reader:
        provider_served = "finney"
        fallback_count = 0
        rate_limit_events = []

        def reset_probe_diagnostics(self):
            pass

        def call(self, method, params):
            if method != "state_queryStorageAt":
                return None, "rpc_error"
            keys = params[0]
            netuid = 64 if keys[0] == map_key_hex(b"SubnetTAO", 64) else 65
            if netuid == 64:
                return [{"changes": bad_changes}], "ok"
            return [{"changes": _good_changes(65)}], "ok"

    mapped = [
        (64, "bittensor", "pool-a", {"base_is_alpha": True}),
        (65, "bittensor", "pool-b", {"base_is_alpha": True}),
    ]
    subs, meta = _live_probe_subnets(mapped, window_hours=48, reader=_Reader())
    assert len(subs) == 2
    assert len(subs[0].matched) == 0
    assert len(subs[1].matched) == 1
    assert meta["per_subnet"][0]["stage_outcome_counts"] == {"reserve_read:malformed_row": 1}
    assert meta["aggregate_stage_outcome_counts"].get("reserve_read:malformed_row") == 1


def test_live_probe_malformed_reserve_row_continues_other_subnets(monkeypatch):
    now_ts = 1_700_000_000
    monkeypatch.setattr(step4_script.time, "time", lambda: float(now_ts))
    monkeypatch.setattr(step4_script, "resolve_block_at", lambda *_a, **_k: (1, "0xabc", "ok"))
    monkeypatch.setattr(
        step4_script,
        "_fetch_gecko_ohlcv",
        lambda *_a, **_k: [[now_ts - 3600, 0, 0, 0, 0.01]],
    )

    def _good_changes(netuid: int) -> list:
        k_tao = map_key_hex(b"SubnetTAO", netuid)
        k_alpha = map_key_hex(b"SubnetAlphaIn", netuid)
        return [[k_tao, "0x0a"], [k_alpha, "0x0a"]]

    class _Reader:
        provider_served = "finney"
        fallback_count = 0
        rate_limit_events = []

        def reset_probe_diagnostics(self):
            pass

        def call(self, method, params):
            if method != "state_queryStorageAt":
                return None, "rpc_error"
            keys = params[0]
            netuid = 64 if keys[0] == map_key_hex(b"SubnetTAO", 64) else 65
            if netuid == 64:
                return [{"changes": [[keys[0]]]}], "ok"
            return [{"changes": _good_changes(65)}], "ok"

    mapped = [
        (64, "bittensor", "pool-a", {"base_is_alpha": True}),
        (65, "bittensor", "pool-b", {"base_is_alpha": True}),
    ]
    subs, meta = _live_probe_subnets(mapped, window_hours=48, reader=_Reader())
    assert len(subs) == 2
    assert len(subs[0].matched) == 0
    assert len(subs[1].matched) == 1
    assert meta["per_subnet"][0]["stage_outcome_counts"] == {"reserve_read:malformed_row": 1}
    assert meta["aggregate_stage_outcome_counts"].get("reserve_read:malformed_row") == 1


def test_live_probe_gecko_error_visible_in_meta(monkeypatch):
    monkeypatch.setattr(
        step4_script,
        "_fetch_gecko_ohlcv",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("gecko_http_429")),
    )

    class _Reader:
        provider_served = None
        fallback_count = 0
        rate_limit_events = []

        def reset_probe_diagnostics(self):
            pass

    subs, meta = _live_probe_subnets(
        [(2, "bittensor", "pool", {"base_is_alpha": True})],
        window_hours=24,
        reader=_Reader(),
    )
    assert subs[0].error == "gecko_fetch:gecko_http_429"
    row = meta["per_subnet"][0]
    assert row["gecko_error"] == "gecko_fetch:gecko_http_429"
    assert meta["aggregate_stage_outcome_counts"].get("gecko_fetch:gecko_http_429") == 1
    report = evaluate_gecko_validation(subs)
    assert report["verdict"] == "INCONCLUSIVE"


def test_live_probe_gecko_http_error_omits_urls_from_diagnostics(monkeypatch):
    import requests

    resp = requests.Response()
    resp.status_code = 404
    resp.url = "https://api.geckoterminal.com/api/v2/networks/foo/pools/bar/ohlcv/hour"
    err = requests.HTTPError(
        f"404 Client Error: Not Found for url: {resp.url}",
        response=resp,
    )

    monkeypatch.setattr(
        step4_script,
        "_fetch_gecko_ohlcv",
        lambda *_a, **_k: (_ for _ in ()).throw(err),
    )

    class _Reader:
        provider_served = None
        fallback_count = 0
        rate_limit_events = []

        def reset_probe_diagnostics(self):
            pass

    subs, meta = _live_probe_subnets(
        [(2, "bittensor", "pool", {"base_is_alpha": True})],
        window_hours=24,
        reader=_Reader(),
    )
    row = meta["per_subnet"][0]
    diag_blob = json.dumps(
        {
            "subnet_error": subs[0].error,
            "gecko_error": row["gecko_error"],
            "stage_outcome_counts": row["stage_outcome_counts"],
            "aggregate_stage_outcome_counts": meta["aggregate_stage_outcome_counts"],
        }
    ).lower()
    assert "geckoterminal" not in diag_blob
    assert "for url" not in diag_blob
    assert subs[0].error == "gecko_fetch:HTTPError"
    assert meta["aggregate_stage_outcome_counts"].get("gecko_fetch:HTTPError") == 1


def test_gecko_fetch_error_label_distinguishes_runtime_codes():
    assert _gecko_fetch_error_label(RuntimeError("gecko_http_429")) == "gecko_fetch:gecko_http_429"
    assert (
        _gecko_fetch_error_label(RuntimeError("unexpected_gecko_shape"))
        == "gecko_fetch:unexpected_gecko_shape"
    )


def test_live_probe_gecko_fetch_stage_keys_differ_for_429_and_shape(monkeypatch):
    outcomes = iter(
        [
            RuntimeError("gecko_http_429"),
            RuntimeError("unexpected_gecko_shape"),
        ]
    )

    def fake_fetch(*_a, **_k):
        raise next(outcomes)

    monkeypatch.setattr(step4_script, "_fetch_gecko_ohlcv", fake_fetch)

    class _Reader:
        provider_served = None
        fallback_count = 0
        rate_limit_events = []

        def reset_probe_diagnostics(self):
            pass

    mapped = [
        (1, "bittensor", "pool-a", {"base_is_alpha": True}),
        (2, "bittensor", "pool-b", {"base_is_alpha": True}),
    ]
    subs, meta = _live_probe_subnets(mapped, window_hours=24, reader=_Reader())
    counts = meta["aggregate_stage_outcome_counts"]
    assert counts.get("gecko_fetch:gecko_http_429") == 1
    assert counts.get("gecko_fetch:unexpected_gecko_shape") == 1
    assert counts.get("gecko_fetch:RuntimeError") is None
    assert subs[0].error == "gecko_fetch:gecko_http_429"
    assert subs[1].error == "gecko_fetch:unexpected_gecko_shape"


def test_live_probe_per_subnet_provider_served_after_reserve_before_close_check(monkeypatch):
    """Replit/Claude MODIFY: finney must appear when reserve ok but close <= 0."""
    now_ts = 1_700_000_000
    monkeypatch.setattr(step4_script.time, "time", lambda: float(now_ts))

    def fake_resolve(_reader, target_ms, search="bracketed"):
        return 1, "0xabc", "ok"

    def fake_reserve(reader, _netuid, _block_hash):
        reader.provider_served = "finney"
        return 0.01, "ok"

    monkeypatch.setattr(step4_script, "resolve_block_at", fake_resolve)
    monkeypatch.setattr(step4_script, "_reserve_price_tao_with_outcome", fake_reserve)
    monkeypatch.setattr(
        step4_script,
        "_fetch_gecko_ohlcv",
        lambda *_a, **_k: [[now_ts - 3600, 0, 0, 0, 0.0]],
    )

    class _Reader:
        provider_served = None
        fallback_count = 0
        rate_limit_events = []

        def reset_probe_diagnostics(self):
            pass

    subs, meta = _live_probe_subnets(
        [(64, "bittensor", "pool", {"base_is_alpha": True})],
        window_hours=48,
        reader=_Reader(),
    )
    assert len(subs[0].matched) == 0
    assert meta["per_subnet"][0]["provider_served"] == "finney"


def test_live_probe_per_subnet_provider_served_not_stale_from_prior_subnet(monkeypatch):
    now_ts = 1_700_000_000
    monkeypatch.setattr(step4_script.time, "time", lambda: float(now_ts))
    probe_netuid = {"current": 1}

    class _Reader:
        provider_served = "finney"
        fallback_count = 0
        rate_limit_events = []

        def reset_probe_diagnostics(self):
            pass

    def fake_fetch(_network, pool, _gt, _limit):
        probe_netuid["current"] = 1 if pool == "pool-a" else 2
        return [[now_ts - 3600, 0, 0, 0, 1.0]]

    def fake_resolve(_reader, target_ms, search="bracketed"):
        if probe_netuid["current"] == 2:
            return None, None, "rate_limited"
        return 1, "0xabc", "ok"

    def fake_reserve(_reader, _netuid, _block_hash):
        return 0.01, "ok"

    monkeypatch.setattr(step4_script, "_fetch_gecko_ohlcv", fake_fetch)
    monkeypatch.setattr(step4_script, "resolve_block_at", fake_resolve)
    monkeypatch.setattr(step4_script, "_reserve_price_tao_with_outcome", fake_reserve)

    mapped = [
        (1, "bittensor", "pool-a", {"base_is_alpha": True}),
        (2, "bittensor", "pool-b", {"base_is_alpha": True}),
    ]
    subs, meta = _live_probe_subnets(mapped, window_hours=48, reader=_Reader())
    assert len(subs[0].matched) == 1
    assert len(subs[1].matched) == 0
    assert meta["per_subnet"][0]["provider_served"] == "finney"
    assert meta["per_subnet"][1]["provider_served"] is None


def test_live_probe_nonpositive_close_counted_in_aggregate(monkeypatch):
    now_ts = 1_700_000_000
    monkeypatch.setattr(step4_script.time, "time", lambda: float(now_ts))
    monkeypatch.setattr(step4_script, "resolve_block_at", lambda *_a, **_k: (1, "0xabc", "ok"))
    monkeypatch.setattr(step4_script, "_reserve_price_tao_with_outcome", lambda *_a: (0.01, "ok"))
    monkeypatch.setattr(
        step4_script,
        "_fetch_gecko_ohlcv",
        lambda *_a, **_k: [[now_ts - 3600, 0, 0, 0, 0.0]],
    )

    class _Reader:
        provider_served = "finney"
        fallback_count = 0
        rate_limit_events = []

        def reset_probe_diagnostics(self):
            pass

    subs, meta = _live_probe_subnets(
        [(64, "bittensor", "pool", {"base_is_alpha": True})],
        window_hours=48,
        reader=_Reader(),
    )
    assert len(subs[0].matched) == 0
    assert meta["per_subnet"][0]["stage_outcome_counts"] == {"gecko_validation:nonpositive_close": 1}
    assert meta["aggregate_stage_outcome_counts"].get("gecko_validation:nonpositive_close") == 1


def test_live_probe_skips_malformed_gecko_rows(monkeypatch):
    now_ts = 1_700_000_000
    monkeypatch.setattr(step4_script.time, "time", lambda: float(now_ts))
    monkeypatch.setattr(step4_script, "resolve_block_at", lambda *_a, **_k: (1, "0xabc", "ok"))
    monkeypatch.setattr(step4_script, "_reserve_price_tao_with_outcome", lambda *_a: (0.01, "ok"))
    malformed = [
        "garbage",
        [1, 2],
        ["bad-ts", 0, 0, 0, 0.01],
        [float("inf"), 0, 0, 0, 0.01],
        [now_ts - 7200, 0, 0, 0, "not-a-number"],
        [now_ts - 5400, 0, 0, 0, None],
        [now_ts - 3600, 0, 0, 0, float("nan")],
    ]
    valid = [now_ts - 10800, 0, 0, 0, 0.01]
    monkeypatch.setattr(
        step4_script,
        "_fetch_gecko_ohlcv",
        lambda *_a, **_k: [*malformed, valid],
    )

    class _Reader:
        provider_served = "finney"
        fallback_count = 0
        rate_limit_events = []

        def reset_probe_diagnostics(self):
            pass

    subs, meta = _live_probe_subnets(
        [(64, "bittensor", "pool", {"base_is_alpha": True})],
        window_hours=48,
        reader=_Reader(),
    )
    assert subs[0].error is None
    assert [m.hour_unix for m in subs[0].matched] == [now_ts - 10800]
    assert meta["per_subnet"][0]["stage_outcome_counts"] == {"gecko_validation:malformed_row": 7}


def test_rpc_call_rate_limited_non_numeric_code_does_not_raise():
    from internal.chain_client import ChainRpcError
    from internal.chain_price.rpc import rpc_call

    class _Client:
        def _call_typed(self, method, params=None):
            raise ChainRpcError("rate_limited", "HTTP 429 too many requests", code="abc")

    client = _Client()
    result, outcome = rpc_call(client, "chain_getBlockHash", [])
    assert result is None
    assert outcome == "rate_limited"
    assert getattr(client, "_last_rate_limit_http_status", None) is None


def test_rpc_call_jsonrpc_code_429_does_not_record_http_status():
    from internal.chain_client import ChainRpcError
    from internal.chain_price.rpc import rpc_call

    class _Client:
        def _call_typed(self, method, params=None):
            raise ChainRpcError("rate_limited", "too many requests", code=429)

    client = _Client()
    result, outcome = rpc_call(client, "chain_getBlockHash", [])
    assert result is None
    assert outcome == "rate_limited"
    assert getattr(client, "_last_rate_limit_http_status", None) is None


def test_rpc_call_clears_stale_rate_limit_status_on_next_call():
    from internal.chain_client import ChainRpcError
    from internal.chain_price.rpc import rpc_call

    class _Client:
        def __init__(self):
            self.attempts = 0

        def _call_typed(self, method, params=None):
            self.attempts += 1
            if self.attempts == 1:
                raise ChainRpcError(
                    "rate_limited", "HTTP 429", code=429, http_status=429
                )
            raise RuntimeError("boom")

    client = _Client()
    _, first = rpc_call(client, "chain_getBlockHash", [])
    assert first == "rate_limited"
    assert client._last_rate_limit_http_status == 429
    _, second = rpc_call(client, "chain_getBlockHash", [])
    assert second == "rpc_error"
    assert not hasattr(client, "_last_rate_limit_http_status")


def test_rpc_call_raw_http_429_records_http_status():
    import requests
    from internal.chain_price.rpc import rpc_call

    resp = requests.Response()
    resp.status_code = 429

    class _Client:
        def _call_typed(self, method, params=None):
            raise requests.HTTPError("429 Client Error: Too Many Requests", response=resp)

    client = _Client()
    result, outcome = rpc_call(client, "chain_getBlockHash", [])
    assert result is None
    assert outcome == "rate_limited"
    assert client._last_rate_limit_http_status == 429


def test_reader_rate_limit_event_jsonrpc_code_429_not_http_status():
    from internal.chain_client import ChainClient, ChainRpcError
    from internal.chain_price.reader import ChainReader

    class _Scripted(ChainClient):
        def __init__(self):
            super().__init__(
                "https://example.invalid/rpc-jsonrpc-429", init_volume_db=False
            )

        def _call_typed(self, method, params=None):
            raise ChainRpcError("rate_limited", "too many requests", code=429)

    reader = ChainReader([("finney", _Scripted())])
    result, outcome = reader.call("chain_getFinalizedHead", [])
    assert result is None
    assert outcome == "rate_limited"
    assert reader.rate_limit_events == [{"provider": "finney", "http_status": None}]


def test_reader_rate_limit_event_includes_http_status():
    from internal.chain_client import ChainClient, ChainRpcError
    from internal.chain_price.reader import ChainReader

    class _Scripted(ChainClient):
        def __init__(self):
            super().__init__(
                "https://example.invalid/rpc-http-429", init_volume_db=False
            )

        def _call_typed(self, method, params=None):
            raise ChainRpcError(
                "rate_limited", "HTTP 429", code=429, http_status=429
            )

    reader = ChainReader([("finney", _Scripted())])
    result, outcome = reader.call("chain_getFinalizedHead", [])
    assert result is None
    assert outcome == "rate_limited"
    assert reader.rate_limit_events == [{"provider": "finney", "http_status": 429}]


def test_conflicting_duplicate_among_eight_clean_fails_gate():
    """Grok MODIFY 6217674797: integrity error must FAIL, not PASS with 8 clean peers."""
    good = [
        SubnetValidationInput(netuid=i, matched=_stamped_aligned_matched(30))
        for i in range(8)
    ]
    bad = SubnetValidationInput(netuid=88, matched=_conflicting_duplicate_stamped_30h())
    report = evaluate_gecko_validation(good + [bad])
    assert report["verdict"] == "FAIL"
    assert report["aggregate"]["qualifying_subnet_count"] == 8
    fail88 = next(f for f in report["failing_subnets"] if f["netuid"] == 88)
    assert fail88["reasons"] == ["data_integrity_error:conflicting_duplicate_hour_unix"]
    ex88 = next(e for e in report["excluded_subnets"] if e["netuid"] == 88)
    assert ex88["matched_hours"] == 31
    assert ex88["reason"] == "conflicting_duplicate_hour_unix"
