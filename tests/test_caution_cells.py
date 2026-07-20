"""Caution Cells — solo ≥6% drawdown / stacked risk flags."""

from internal.simivision import caution_cells as cc


def test_solo_anticipated_drawdown(monkeypatch, tmp_path):
    monkeypatch.setattr(cc, "SEEN_PATH", str(tmp_path / "seen.json"))
    monkeypatch.setattr(cc, "_already_flagged", lambda nu: False)
    monkeypatch.setattr(cc, "_mark_flagged", lambda nu: None)

    monkeypatch.setattr(
        "internal.council.state_vector.score_subnet_for_day",
        lambda sn, ctx: {
            "signal_impact": {
                "net_predicted_pct": -7.2,
                "dominant": None,
            }
        },
    )
    monkeypatch.setattr(
        "internal.council.dark_horse_crash.crash_tail_features",
        lambda sn: {"drawdown_pct": -1.0},
    )
    monkeypatch.setattr(
        "internal.subnet_names.name_for_netuid",
        lambda nu: "DangerSN",
    )

    cell = cc.evaluate_subnet_caution({"netuid": 11, "name": "DangerSN"})
    assert cell is not None
    assert cell["solo"] is True
    assert "anticipated" in cell["reasons"][0]
    assert "CAUTION" == cell["label"]


def test_needs_stack_without_solo(monkeypatch, tmp_path):
    monkeypatch.setattr(cc, "SEEN_PATH", str(tmp_path / "seen.json"))
    monkeypatch.setattr(cc, "_already_flagged", lambda nu: False)

    monkeypatch.setattr(
        "internal.council.state_vector.score_subnet_for_day",
        lambda sn, ctx: {
            "signal_impact": {
                "net_predicted_pct": -2.0,
                "dominant": "SELL ALERT",
            }
        },
    )
    monkeypatch.setattr(
        "internal.council.dark_horse_crash.crash_tail_features",
        lambda sn: {"drawdown_pct": -1.0},
    )
    monkeypatch.setattr(
        "internal.subnet_names.name_for_netuid",
        lambda nu: "Mild",
    )

    # Only one stack flag (distribution) — should not fire
    assert cc.evaluate_subnet_caution({"netuid": 3}) is None
    # distribution + fading = 2 → fire
    cell = cc.evaluate_subnet_caution({"netuid": 3}, fading=True)
    assert cell is not None
    assert cell["solo"] is False


def test_build_respects_cap_and_excludes_call(monkeypatch, tmp_path):
    monkeypatch.setattr(cc, "SEEN_PATH", str(tmp_path / "seen.json"))
    monkeypatch.setattr(cc, "_already_flagged", lambda nu: False)
    monkeypatch.setattr(cc, "_mark_flagged", lambda nu: None)
    monkeypatch.setattr(
        "internal.learning.trail_bus.emit_signal_triggered",
        lambda **kw: None,
    )
    monkeypatch.setattr(
        "internal.subnets.tradable.subnet_volume",
        lambda sn: float(sn.get("volume") or 0),
    )

    def _score(sn, ctx):
        return {
            "signal_impact": {
                "net_predicted_pct": -8.0,
                "dominant": None,
            }
        }

    monkeypatch.setattr("internal.council.state_vector.score_subnet_for_day", _score)
    monkeypatch.setattr(
        "internal.council.dark_horse_crash.crash_tail_features",
        lambda sn: {"drawdown_pct": 0.0},
    )
    monkeypatch.setattr(
        "internal.subnet_names.name_for_netuid",
        lambda nu: f"SN{nu}",
    )

    subnets = [
        {"netuid": 1, "name": "Call", "volume": 999},
        {"netuid": 2, "name": "A", "volume": 100},
        {"netuid": 3, "name": "B", "volume": 90},
        {"netuid": 4, "name": "C", "volume": 80},
        {"netuid": 5, "name": "D", "volume": 70},
    ]
    daily = {"pick": {"subnet": {"netuid": 1}, "final_confidence": 0.8}}
    cells = cc.build_caution_cells(subnets, daily_pick=daily, limit=3)
    assert len(cells) <= 3
    assert all(c["netuid"] != 1 for c in cells)
