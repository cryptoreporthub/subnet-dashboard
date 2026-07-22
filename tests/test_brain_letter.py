"""§21 L11 — brain letter (RF-2 honest accuracy)."""

from internal.learning.trust_stats import build_trust_banner
from internal.letter.brain_letter import build_brain_letter, _outlook_sentence


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
            "outlook": "No sized call this window — watching the desk into resolve.",
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
    assert "audit gate" not in out["markdown"].lower()
    assert out.get("outlook")
    assert "## Next" in out["markdown"]
    assert "## What changed since yesterday" in out["markdown"]
    assert "## How we got here" not in out["markdown"]


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
            "resolves_in": "4h",
            "horizon": "24h",
            "outlook": "Into the next 4h we expect follow-through while liquidity holds.",
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
    assert out["outlook"]
    md = out["markdown"]
    assert md.index("## What changed since yesterday") < md.index("## Today")
    assert md.index("## Today") < md.index("## Next")
    assert md.index("## Next") < md.index("## Integrity")


def test_brain_letter_wave3_fields(monkeypatch):
    monkeypatch.setattr(
        "internal.letter.brain_letter._today_pick_block",
        lambda: {
            "date": "2026-07-16",
            "action": "HOLD",
            "published": False,
            "name": "Taoshi",
            "outlook": "No sized call this window — watching the desk into resolve.",
        },
    )
    monkeypatch.setattr(
        "internal.letter.brain_letter._trust_block",
        lambda: {
            "trust_banner": build_trust_banner({"correct": 5, "wrong": 5, "expired": 0, "total": 10}),
            "brain_ui_ready": False,
            "watchdog": {},
        },
    )
    monkeypatch.setattr(
        "internal.letter.brain_letter._working_block",
        lambda: {"ready": False, "top_price_signals": [], "disclaimer": ""},
    )
    monkeypatch.setattr(
        "internal.letter.brain_letter._story_block",
        lambda: {"data_available": False, "steps": []},
    )
    monkeypatch.setattr(
        "internal.letter.brain_letter._yesterday_graded_outcome",
        lambda: "Yesterday · Taoshi · HIT · +2.1% actual",
    )
    monkeypatch.setattr(
        "internal.letter.brain_letter._new_subnet_seed_strip",
        lambda limit=5: [{"netuid": 120, "name": "NewNet", "note": "verify on desk"}],
    )

    out = build_brain_letter()
    assert out["yesterday_outcome"].startswith("Yesterday")
    assert out["seed_strip"][0]["netuid"] == 120
    assert "SimiVision desk" in out["desk_block"]
    assert "Taoshi" in out["desk_block"]


def test_outlook_hold_candidate():
    outlook = _outlook_sentence(
        {
            "action": "HOLD",
            "published": False,
            "name": "Taoshi",
            "resolves_in": "4h",
            "trigger": "conviction clears 45%",
        }
    )
    assert "stay flat" in outlook.lower()
    assert "4h" in outlook
    assert len(outlook) <= 140


def test_outlook_quiet_desk():
    outlook = _outlook_sentence({"action": "HOLD", "published": False, "name": None})
    assert outlook == "No sized call this window — watching the desk into resolve."
