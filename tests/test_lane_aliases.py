"""Lane alias nicknames after version bumps."""

from internal.council.lane_aliases import version_nickname, version_paper_twist, version_promotion
from internal.council.formula_evolution import build_evolution_trail


def test_version_nickname_deterministic():
    assert version_nickname("dark_horse", "1.1", "Dark Horse") == "Darker Horse"
    assert version_nickname("dark_horse", "1.2", "Dark Horse") == "Midnight Stallion"
    assert version_nickname("dark_horse", "1.3", "Dark Horse") == "Shadow Pony LLC"


def test_version_paper_twist_dark_horse():
    assert version_paper_twist("dark_horse", "1.1") == "Forecasting Crashes with a Wince"
    assert version_paper_twist("dark_horse", "1.3") == "Forecasting Crashes with a Frown"


def test_version_promotion_hybrid():
    promo = version_promotion("dark_horse", "1.3", "Dark Horse")
    assert promo["nickname"] == "Shadow Pony LLC"
    assert promo["paper_title"] == "Forecasting Crashes with a Smile"
    assert promo["paper_twist"] == "Forecasting Crashes with a Frown"


def test_evolution_trail_nickname_after_version_bump(monkeypatch):
    monkeypatch.setattr(
        "internal.council.formula_evolution._lane_predictions",
        lambda lane: [],
    )
    monkeypatch.setattr("internal.council.formula_evolution._weight_events", lambda lane: [])
    monkeypatch.setattr("internal.council.formula_evolution._calibration_episodes", lambda: [])
    monkeypatch.setattr(
        "internal.council.formula_evolution._version_episodes",
        lambda lane: [
            {
                "day": "2026-07-18",
                "version": "1.3",
                "previous_version": "1.2",
                "beat_previous": True,
                "story": "v1.3 beat v1.2 on holdout.",
                "before": 0.17,
                "after": 0.18,
            }
        ],
    )

    trail = build_evolution_trail("dark_horse")
    kinds = [e["kind"] for e in trail["trail"]]
    assert "version_upgrade" in kinds
    assert "version_nickname" in kinds
    upgrade_i = kinds.index("version_upgrade")
    nickname_i = kinds.index("version_nickname")
    assert nickname_i == upgrade_i + 1
    nick_ep = trail["trail"][nickname_i]
    assert nick_ep["nickname"] == "Shadow Pony LLC"
    assert nick_ep["paper_twist"] == "Forecasting Crashes with a Frown"
    assert "Forecasting Crashes with a Smile" in nick_ep["narrative"]
    assert "HR paperwork" in nick_ep["narrative"]
