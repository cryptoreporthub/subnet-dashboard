"""§21 L11 — brain letter (RF-2 honest accuracy)."""

from internal.learning.trust_stats import build_trust_banner
from internal.letter.brain_letter import build_brain_letter


def test_brain_letter_uses_trust_banner_not_hardcoded(monkeypatch):
    monkeypatch.setattr(
        "internal.letter.brain_letter._today_pick_block",
        lambda: {
            "date": "2026-07-16",
            "action": "HOLD",
            "published": False,
            "name": None,
            "why": "Gate pending",
            "driver_card": None,
        },
    )
    monkeypatch.setattr(
        "internal.letter.brain_letter._trust_block",
        lambda: {
            "trust_banner": build_trust_banner(
                {"correct": 15, "wrong": 19, "expired": 16, "total": 50}
            ),
            "brain_ui_ready": False,
            "watchdog": {"warning": True, "reason": "high expired rate"},
        },
    )
    monkeypatch.setattr(
        "internal.letter.brain_letter._working_block",
        lambda: {"ready": False, "top_price_signals": [], "disclaimer": "test"},
    )
    monkeypatch.setattr(
        "internal.letter.brain_letter._story_block",
        lambda: {"data_available": False, "steps": []},
    )

    out = build_brain_letter()
    assert out["status"] == "ok"
    assert out["brain_ui_ready"] is False
    assert "58%" not in out["markdown"]
    assert out["trust_banner"]["message"] is not None or out["trust_banner"]["headline"] is None
    assert "Resolver backlog" in out["markdown"] or "expired" in out["markdown"].lower()


def test_brain_letter_shows_real_accuracy_when_ready(monkeypatch):
    monkeypatch.setattr(
        "internal.letter.brain_letter._today_pick_block",
        lambda: {
            "date": "2026-07-16",
            "action": "BUY",
            "published": True,
            "name": "Taoshi",
            "netuid": 8,
            "why": "Momentum",
            "driver_card": {"status": "success", "decomposition": {"yield_trap": True}},
        },
    )
    banner = build_trust_banner(
        {"correct": 40, "wrong": 35, "expired": 2, "total": 80},
        watchdog={"warning": False},
    )
    monkeypatch.setattr(
        "internal.letter.brain_letter._trust_block",
        lambda: {"trust_banner": banner, "brain_ui_ready": banner["ready"], "watchdog": {}},
    )
    monkeypatch.setattr(
        "internal.letter.brain_letter._working_block",
        lambda: {
            "ready": True,
            "top_price_signals": [{"signal": "delegation_flow", "hit_rate": 0.55, "n": 12}],
            "disclaimer": "",
        },
    )
    monkeypatch.setattr(
        "internal.letter.brain_letter._story_block",
        lambda: {
            "data_available": True,
            "steps": [{"label": "1 · Signals", "title": "delegation flow"}],
        },
    )

    out = build_brain_letter()
    assert banner["ready"] is True
    assert "75%" in out["markdown"] or "Last 75" in out["markdown"]
    assert "Taoshi" in out["markdown"]
    assert "delegation" in out["markdown"].lower()
