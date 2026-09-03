"""report.py percent formatting — honest em-dash, never a dangling '%'. (\u2014%) bug."""
from __future__ import annotations

from unittest.mock import patch

from internal.analytics.report import _fmt_pct, build_subnet_report


def test_fmt_pct_renders_value_with_percent():
    assert _fmt_pct(4.2) == "4.2%"
    assert _fmt_pct(0) == "0%"


def test_fmt_pct_bare_emdash_when_missing():
    assert _fmt_pct(None) == "\u2014"


def test_fmt_pct_bare_emdash_when_already_placeholder():
    assert _fmt_pct("\u2014") == "\u2014"


def test_empty_report_markdown_never_renders_emdash_percent():
    with patch("server._get_subnets_with_source", return_value=([], "test")):
        out = build_subnet_report(999)
    assert out["status"] == "empty"
    assert "\u2014%" not in out["markdown"]
