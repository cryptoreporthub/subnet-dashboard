"""Acc-1 archive measurement script tests."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.measure_accuracy_archive import (
    build_summary,
    iter_resolved,
    load_archive,
    measure_archive,
    render_markdown,
)


FIXTURE = Path("tests/fixtures/acc1_archive_sample.json")


def test_load_archive_file():
    data = load_archive(str(FIXTURE))
    rows = iter_resolved(data)
    assert len(rows) == 5


def test_horizon_compare_fixture():
    data = load_archive(str(FIXTURE))
    summary = build_summary(iter_resolved(data), str(FIXTURE))
    assert summary["overall"]["n"] == 5
    assert summary["horizon_compare"]["verdict"] in {"24h_better", "4h_better", "similar", "inconclusive"}
    assert summary["noise_misses"]["misses"] >= 1


def test_measure_archive_writes_outputs(tmp_path):
    out_json = tmp_path / "acc1.json"
    out_md = tmp_path / "acc1.md"
    summary, report = measure_archive(str(FIXTURE))
    out_json.write_text(json.dumps(summary), encoding="utf-8")
    out_md.write_text(report, encoding="utf-8")
    assert summary["overall"]["n"] == 5
    assert "4h vs 24h horizon" in report
    assert "Recommendations" in report


def test_render_markdown_answers_key_questions():
    data = load_archive(str(FIXTURE))
    summary = build_summary(iter_resolved(data), str(FIXTURE))
    md = render_markdown(summary)
    assert "Expert breakdown" in md
    assert "Magnitude noise" in md
    assert "quant" in md.lower()
