"""Streak + judge-audit learning loop tests."""

from internal.learning.streaks import STREAK_THRESHOLD, compute_streaks


def test_council_streak_activates_at_threshold():
    data = {
        "resolved": [
            {"netuid": 1, "correct": True, "expert": "quant", "resolved_at": "2026-07-01T01:00:00Z", "outcome": "hit"},
            {"netuid": 2, "correct": True, "expert": "hype", "resolved_at": "2026-07-01T02:00:00Z", "outcome": "hit"},
            {"netuid": 3, "correct": True, "expert": "quant", "resolved_at": "2026-07-01T03:00:00Z", "outcome": "hit"},
        ]
    }
    out = compute_streaks(data)
    assert out["council"]["length"] == 3
    assert out["council"]["active"] is True
    assert out["whisper"] and "Council · 3 in a row" in out["whisper"]
    assert out["threshold"] == STREAK_THRESHOLD


def test_miss_clears_council_streak():
    data = {
        "resolved": [
            {"netuid": 1, "correct": True, "expert": "quant", "resolved_at": "2026-07-01T01:00:00Z", "outcome": "hit"},
            {"netuid": 2, "correct": True, "expert": "quant", "resolved_at": "2026-07-01T02:00:00Z", "outcome": "hit"},
            {"netuid": 3, "correct": True, "expert": "quant", "resolved_at": "2026-07-01T03:00:00Z", "outcome": "hit"},
            {"netuid": 4, "correct": False, "expert": "quant", "resolved_at": "2026-07-01T04:00:00Z", "outcome": "miss"},
        ]
    }
    out = compute_streaks(data)
    assert out["council"]["length"] == 0
    assert out["council"]["active"] is False
    assert out["whisper"] is None


def test_expert_streak_independent():
    data = {
        "resolved": [
            {"netuid": 1, "correct": True, "expert": "quant", "resolved_at": "2026-07-01T01:00:00Z", "outcome": "hit"},
            {"netuid": 2, "correct": False, "expert": "hype", "resolved_at": "2026-07-01T02:00:00Z", "outcome": "miss"},
            {"netuid": 3, "correct": True, "expert": "quant", "resolved_at": "2026-07-01T03:00:00Z", "outcome": "hit"},
            {"netuid": 4, "correct": True, "expert": "quant", "resolved_at": "2026-07-01T04:00:00Z", "outcome": "hit"},
            {"netuid": 5, "correct": True, "expert": "quant", "resolved_at": "2026-07-01T05:00:00Z", "outcome": "hit"},
        ]
    }
    out = compute_streaks(data)
    # Council chronological: T,F,T,T,T → streak 3
    assert out["council"]["length"] == 3
    # Quant-only rows are all hits → streak 4
    assert out["experts"]["quant"]["length"] == 4
    assert out["experts"]["quant"]["active"] is True
    assert out["experts"]["hype"]["length"] == 0


def test_judge_audit_nudge_half_strength(monkeypatch, tmp_path):
    from internal.council import resolver, weights

    path = str(tmp_path / "soul_map.json")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", path)
    weights.save_weights(
        {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0},
        path,
    )
    monkeypatch.setattr(resolver, "_in_replay_mode", lambda: False)

    trails = []

    def _emit(expert, **kwargs):
        trails.append({"expert": expert, **kwargs})

    monkeypatch.setattr("internal.learning.trail_bus.emit_weight_change", _emit)

    pred = {
        "judge_scores_at_creation": {
            "oracle": {"score": 0.9},
            "echo": {"score": 0.4},
            "pulse": {"score": 0.5},
        }
    }
    resolver._nudge_weights_from_judge_audit(pred, True)
    w = weights.load_weights(path)
    assert abs(w["quant"] - 1.01) < 1e-6
    assert abs(w["technical"] - 1.01) < 1e-6
    assert abs(w["hype"] - 1.0) < 1e-6
    assert any(t.get("reason") == "judge_audit_resolve" for t in trails)


def test_trust_banner_includes_streak_whisper(monkeypatch):
    from internal.learning.trust_stats import build_trust_banner

    monkeypatch.setattr(
        "internal.learning.streaks.compute_streaks",
        lambda: {
            "council": {"length": 4, "active": True, "label": "Council · 4 in a row"},
            "experts": {},
            "whisper": "Council · 4 in a row",
            "threshold": 3,
        },
    )
    banner = build_trust_banner({"correct": 40, "wrong": 10, "expired": 1, "total": 51})
    assert banner["streak_whisper"] == "Council · 4 in a row"
