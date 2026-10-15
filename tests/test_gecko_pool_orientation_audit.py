"""Tests for scripts/gecko_pool_orientation_audit.py (rate limit + 429 handling)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import requests

from scripts.gecko_pool_orientation_audit import (
    MAX_CALLS_PER_MINUTE,
    MIN_REQUEST_INTERVAL_S,
    _fetch_pool,
    _parse_retry_after,
    _RequestPacer,
    _retry_delay_seconds,
    audit_pairs,
    main,
)


class _FakeResp:
    def __init__(self, status_code: int, headers=None, payload=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"http {self.status_code}")

    def json(self):
        return self._payload


def test_min_interval_paces_under_30_per_minute():
    assert MAX_CALLS_PER_MINUTE <= 30
    assert MIN_REQUEST_INTERVAL_S >= 60.0 / 30.0


def test_request_pacer_waits_for_remaining_interval():
    clock = [0.0]
    sleeps: list[float] = []

    def mono():
        return clock[0]

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock[0] += seconds

    pacer = _RequestPacer(min_interval_s=2.0, monotonic=mono, sleep=fake_sleep)
    pacer.wait_turn()
    clock[0] = 0.5
    pacer.wait_turn()
    assert sleeps == [1.5]


def test_429_honors_retry_after_before_retry(monkeypatch):
    sleeps: list[float] = []
    calls: list[int] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def fake_get(url, params=None, timeout=30):
        calls.append(1)
        if len(calls) == 1:
            return _FakeResp(429, headers={"Retry-After": "4"})
        return _FakeResp(
            200,
            payload={
                "data": {
                    "attributes": {"name": "SN1 / TAO"},
                    "relationships": {
                        "base_token": {"data": {"id": "bittensor_1"}},
                        "quote_token": {"data": {"id": "bittensor_0"}},
                    },
                }
            },
        )

    payload, err = _fetch_pool(
        "bittensor",
        "0-1",
        max_attempts=3,
        pacer=None,
        sleep=fake_sleep,
        get=fake_get,
    )
    assert err is None
    assert payload is not None
    assert sleeps[0] == 4.0
    assert all(s >= 4.0 for s in sleeps[:1])


def test_429_no_early_retry_under_retry_after(monkeypatch):
    """First backoff must be >= Retry-After (not a sub-second exponential retry)."""
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def fake_get(url, params=None, timeout=30):
        return _FakeResp(429, headers={"Retry-After": "10"})

    payload, err = _fetch_pool(
        "bittensor",
        "0-1",
        max_attempts=2,
        pacer=None,
        sleep=fake_sleep,
        get=fake_get,
    )
    assert payload is None
    assert err == "http_429_exhausted"
    assert sleeps
    assert not any(s < 10.0 for s in sleeps)
    assert sleeps[0] == 10.0


def test_429_exhaustion_marks_unknown_and_nonzero_exit():
    def fake_get(url, params=None, timeout=30):
        return _FakeResp(429, headers={"Retry-After": "1"})

    pairs = {
        "1": {
            "geckoterminal": {"network": "bittensor", "pool": "0-1", "base_is_alpha": True}
        }
    }
    noop_pacer = _RequestPacer(min_interval_s=0, monotonic=lambda: 0.0, sleep=lambda _s: None)
    report = audit_pairs(
        pairs, pacer=noop_pacer, sleep=lambda _s: None, get=fake_get
    )
    assert report["unknown_or_error_count"] == 1
    row = report["rows"][0]
    assert row["orientation"] == "unknown"
    assert row["error"] == "http_429_exhausted"


def test_non_http_exception_is_not_retried():
    """Connection-level errors stop after one attempt (no retry, no sleep)."""
    calls: list[int] = []
    sleeps: list[float] = []

    def fake_get(url, params=None, timeout=30):
        calls.append(1)
        raise requests.ConnectionError("connection reset")

    payload, err = _fetch_pool(
        "bittensor",
        "0-1",
        max_attempts=6,
        pacer=None,
        sleep=sleeps.append,
        get=fake_get,
    )
    assert payload is None
    assert err == "connection reset"
    assert len(calls) == 1
    assert sleeps == []


def test_main_exits_nonzero_on_audit_errors(tmp_path, monkeypatch):
    pairs_path = tmp_path / "price_pairs.json"
    pairs_path.write_text(
        json.dumps(
            {
                "1": {
                    "geckoterminal": {
                        "network": "bittensor",
                        "pool": "0-1",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    def fake_get(url, params=None, timeout=30):
        return _FakeResp(429, headers={"Retry-After": "2"})

    monkeypatch.setattr(
        "scripts.gecko_pool_orientation_audit.requests.get",
        fake_get,
    )
    monkeypatch.setattr(
        "scripts.gecko_pool_orientation_audit.write_artifacts",
        lambda _report: None,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["gecko_pool_orientation_audit.py", "--pairs-path", str(pairs_path)],
    )
    assert main() == 1


def test_parse_retry_after_and_fallback():
    resp = _FakeResp(429, headers={"Retry-After": "7"})
    assert _parse_retry_after(resp) == 7.0
    assert _retry_delay_seconds(resp, 0) == 7.0
    bare = _FakeResp(429)
    assert _retry_delay_seconds(bare, 0) >= 30.0
