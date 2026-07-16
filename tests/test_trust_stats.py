"""Trust banner + resolver integrity (Ditto RF-2 / RF-3)."""

from internal.learning.trust_stats import build_trust_banner


def test_trust_banner_honest_empty_low_sample():
    banner = build_trust_banner({"correct": 5, "wrong": 4, "expired": 2, "total": 20})
    assert banner["ready"] is False
    assert banner["headline"] is None
    assert "not enough" in banner["message"].lower()


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
