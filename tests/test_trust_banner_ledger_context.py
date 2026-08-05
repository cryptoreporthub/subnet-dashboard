"""Phase 1 — dual-count trust banner (published vs ledger 30d)."""

from internal.learning.trust_stats import build_trust_banner


def test_trust_banner_includes_ledger_context_when_thin_published_sample():
    banner = build_trust_banner(
        {"correct": 1, "wrong": 0, "expired": 0, "total": 1, "shadow_graded": 21},
        min_graded=30,
        ledger_context={
            "data_available": True,
            "graded_30d": 189,
            "hit_rate_30d": 0.1323,
        },
    )
    assert banner["graded"] == 1
    assert banner["ready"] is False
    assert banner["ledger_graded_30d"] == 189
    assert banner["ledger_hit_rate_30d"] == 0.1323
    assert banner["ledger_note"]
    assert "published LONG" in banner["ledger_note"]


def test_trust_banner_omits_ledger_when_context_missing():
    banner = build_trust_banner(
        {"correct": 1, "wrong": 0, "expired": 0, "total": 1},
        min_graded=30,
    )
    assert banner.get("ledger_graded_30d") is None
    assert banner.get("ledger_hit_rate_30d") is None


def test_trust_banner_ready_unchanged_with_ledger_context():
    banner = build_trust_banner(
        {"correct": 35, "wrong": 25, "expired": 5, "total": 70},
        ledger_context={"data_available": True, "graded_30d": 200, "hit_rate_30d": 0.15},
    )
    assert banner["ready"] is True
    assert banner["headline"] is not None
