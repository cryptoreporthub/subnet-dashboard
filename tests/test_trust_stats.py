"""Trust banner + resolver integrity (Ditto RF-2 / RF-3)."""

from internal.learning.trust_stats import build_trust_banner


def test_trust_banner_honest_empty_low_sample():
    banner = build_trust_banner({"correct": 5, "wrong": 4, "expired": 2, "total": 20})
    assert banner["ready"] is False
    assert banner["headline"] is None
    assert "not enough" in banner["message"].lower()


def test_trust_banner_explains_hold_shadows_excluded():
    banner = build_trust_banner(
        {"correct": 1, "wrong": 0, "expired": 0, "total": 1, "shadow_graded": 21},
        min_graded=30,
    )
    assert banner["ready"] is False
    assert banner["graded"] == 1
    assert banner["shadow_graded"] == 21
    assert "shadow" in banner["message"].lower()
    assert "1/30" in banner["message"]
    assert banner["min_graded"] == 30


def test_trust_banner_blocks_high_expired_rate():
    banner = build_trust_banner(
        {"correct": 40, "wrong": 35, "expired": 30, "total": 105},
        min_graded=30,
        max_expired_rate=0.10,
    )
    assert banner["accuracy"] == round(40 / 75, 3)
    assert banner["ready"] is False
    assert "expired" in banner["message"].lower()
    assert banner["headline"] is None


def test_trust_banner_shows_real_accuracy_not_target():
    banner = build_trust_banner(
        {"correct": 15, "wrong": 19, "expired": 16, "total": 59},
        min_graded=30,
        max_expired_rate=0.10,
    )
    assert banner["accuracy"] == round(15 / 34, 3)
    assert banner["ready"] is False
    assert banner["headline"] is None
    assert "expired" in (banner["message"] or "").lower()


def test_trust_banner_ready_when_gates_pass():
    banner = build_trust_banner(
        {"correct": 35, "wrong": 25, "expired": 5, "total": 70},
        watchdog={"warning": False},
    )
    assert banner["ready"] is True
    assert banner["headline"] is not None
    assert "58" in banner["headline"]


def test_trust_banner_exposes_missing_price_retirements_separately():
    banner = build_trust_banner(
        {
            "correct": 0,
            "wrong": 0,
            "expired": 4,
            "expired_genuine": 1,
            "ungradeable": 3,
            "price_data_unavailable": 3,
            "total": 7,
        }
    )
    assert banner["expired_genuine"] == 1
    assert banner["ungradeable"] == 3
    assert banner["price_data_unavailable"] == 3
    assert "resolved-flow" in banner["message"]


def test_trust_banner_keeps_council_and_pump_pending_separate():
    banner = build_trust_banner(
        {
            "correct": 0,
            "wrong": 0,
            "expired": 0,
            "pending": 2,
            "council_pending": 2,
            "pump_pending": 6,
            "total_pending": 8,
        }
    )
    assert banner["pending"] == 2
    assert banner["council_pending"] == 2
    assert banner["pump_pending"] == 6
    assert banner["total_pending"] == 8
