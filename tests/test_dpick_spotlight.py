"""Hero spotlight swaps bearish expert tails for weighing-board desk leads."""

from __future__ import annotations

from internal.council.publish_gate import directional_publish_guard
from internal.learning.dpick_spotlight import attach_hero_spotlight_candidate
from internal.simivision.weighing_room import shape_weighing_board


def test_spotlight_replaces_bearish_expert_candidate(monkeypatch):
    expert = {
        "subnet": {"netuid": 13, "name": "Data Universe"},
        "final_confidence": 0.58,
        "signal_impact": {"net_direction": "bearish", "net_predicted_pct": -0.58},
    }
    assert directional_publish_guard(expert)["approved"] is False

    monkeypatch.setattr(
        "internal.simivision.weighing_room.build_weighing_candidates_from_shortlist",
        lambda subnets, daily_pick, market_context: (
            [
                {
                    "netuid": 25,
                    "name": "Mainframe",
                    "conviction": 89,
                    "judge_long": True,
                    "judge_scores": {
                        "oracle": {"score": 0.9, "confidence": 0.9},
                        "echo": {"score": 0.85, "confidence": 0.85},
                        "pulse": {"score": 0.8, "confidence": 0.8},
                    },
                }
            ],
            10,
        ),
    )
    payload = {
        "action": "HOLD",
        "pick": None,
        "candidate": expert,
        "reason": "Directional conflict: council signal is bearish; no LONG published.",
    }
    out = attach_hero_spotlight_candidate(payload, [{"netuid": 25, "name": "Mainframe"}])
    assert out["hero_spotlight_source"] == "judge_long"
    assert out["candidate"]["subnet"]["netuid"] == 25
    assert out["desk_candidate"]["subnet"]["netuid"] == 13


def test_spotlight_picks_highest_conviction_not_cache_order(monkeypatch):
    """Weighing board sorts by conviction — hero must match, not raw judge-cache order."""
    monkeypatch.setattr(
        "internal.simivision.weighing_room.build_weighing_candidates_from_shortlist",
        lambda subnets, daily_pick, market_context: (
            [
                {"netuid": 93, "name": "Bitcast", "conviction": 72, "judge_long": True},
                {"netuid": 25, "name": "Mainframe", "conviction": 89, "judge_long": True},
            ],
            10,
        ),
    )
    payload = {
        "action": "HOLD",
        "pick": None,
        "reason": "Directional conflict: council signal is bearish; no LONG published.",
        "candidate": {
            "subnet": {"netuid": 13, "name": "Data Universe"},
            "final_confidence": 0.58,
        },
    }
    out = attach_hero_spotlight_candidate(payload, [{"netuid": 25, "name": "Mainframe"}])
    assert out["candidate"]["subnet"]["netuid"] == 25
    assert out["hero_spotlight_source"] == "judge_long"


def test_spotlight_skips_when_weighing_not_better(monkeypatch):
    monkeypatch.setattr(
        "internal.simivision.weighing_room.build_weighing_candidates_from_shortlist",
        lambda subnets, daily_pick, market_context: (
            [{"netuid": 13, "name": "Data Universe", "conviction": 40, "judge_long": True}],
            5,
        ),
    )
    expert = {
        "subnet": {"netuid": 13, "name": "Data Universe"},
        "final_confidence": 0.58,
        "signal_impact": {"net_direction": "bearish", "net_predicted_pct": -0.58},
    }
    payload = {
        "action": "HOLD",
        "pick": None,
        "candidate": expert,
        "reason": "Directional conflict: council signal is bearish; no LONG published.",
    }
    out = attach_hero_spotlight_candidate(payload, [{"netuid": 13, "name": "Data Universe"}])
    assert "hero_spotlight_source" not in out
    assert out.get("hero_spotlight_blocked") is True
    assert "candidate" not in out
    assert out["desk_candidate"]["subnet"]["netuid"] == 13


def test_spotlight_keeps_nonconflicting_candidate(monkeypatch):
    expert = {
        "subnet": {"netuid": 4, "name": "Targon"},
        "final_confidence": 0.72,
        "signal_impact": {"net_direction": "bullish", "net_predicted_pct": 0.4},
    }
    monkeypatch.setattr(
        "internal.simivision.weighing_room.build_weighing_candidates_from_shortlist",
        lambda subnets, daily_pick, market_context: (
            [{"netuid": 25, "name": "Mainframe", "conviction": 89, "judge_long": True}],
            10,
        ),
    )
    out = attach_hero_spotlight_candidate(
        {"action": "HOLD", "pick": None, "candidate": expert},
        [{"netuid": 25, "name": "Mainframe"}],
    )
    assert out["candidate"]["subnet"]["netuid"] == 4
    assert "hero_spotlight_source" not in out


def test_spotlight_uses_payload_reason_when_signal_impact_missing(monkeypatch):
    monkeypatch.setattr(
        "internal.simivision.weighing_room.build_weighing_candidates_from_shortlist",
        lambda subnets, daily_pick, market_context: (
            [
                {"netuid": 0, "name": "Root", "conviction": 99, "judge_long": True},
                {"netuid": 25, "name": "Mainframe", "conviction": 89, "judge_long": True},
            ],
            10,
        ),
    )
    payload = {
        "action": "HOLD",
        "pick": None,
        "reason": "Directional conflict: council signal is bearish; no LONG published.",
        "candidate": {
            "subnet": {"netuid": 13, "name": "Data Universe"},
            "final_confidence": 0.58,
        },
    }
    out = attach_hero_spotlight_candidate(payload, [{"netuid": 25, "name": "Mainframe"}])
    assert out["hero_spotlight_source"] == "judge_long"
    assert out["candidate"]["subnet"]["netuid"] == 25
    assert out["desk_candidate"]["subnet"]["netuid"] == 13


def test_shape_board_no_false_stitch_without_call_context():
    top = [
        {
            "netuid": 25,
            "name": "Mainframe",
            "conviction": 89,
            "judge_long": True,
            "why_not": "Judge consensus 89%",
        }
    ]
    rows, meta = shape_weighing_board(top, pool_count=10, daily_pick=None)
    assert meta["call_netuid"] is None
    assert rows[0]["netuid"] == 25
    assert rows[0].get("closest_to_call") is not True


def test_spotlight_uses_shaped_weighing_rows_when_provided():
    payload = {
        "action": "HOLD",
        "pick": None,
        "reason": "Directional conflict: council signal is bearish; no LONG published.",
        "candidate": {
            "subnet": {"netuid": 13, "name": "Data Universe"},
            "final_confidence": 0.58,
        },
    }
    shaped = [
        {
            "netuid": 13,
            "name": "Data Universe",
            "conviction": 58,
            "primary_call": True,
            "closest_to_call": True,
        },
        {
            "netuid": 25,
            "name": "Mainframe",
            "conviction": 89,
            "judge_long": True,
            "closest_to_call": False,
            "gap_whisper": "31 pts above the call bar",
        },
    ]
    from internal.learning.dpick_spotlight import attach_hero_spotlight_from_weighing_rows

    out = attach_hero_spotlight_from_weighing_rows(payload, shaped)
    assert out["hero_spotlight_source"] == "judge_long"
    assert out["candidate"]["subnet"]["netuid"] == 25


def test_weighing_lead_prefers_closest_to_call_on_conviction_tie():
    from internal.simivision.weighing_room import weighing_lead_from_rows

    rows = [
        {"netuid": 13, "conviction": 58, "primary_call": True},
        {"netuid": 9, "conviction": 89, "proximity": 69, "judge_long": False},
        {
            "netuid": 25,
            "conviction": 89,
            "proximity": 69,
            "judge_long": True,
            "closest_to_call": True,
        },
        {"netuid": 65, "conviction": 89, "proximity": 69, "judge_long": True},
    ]
    lead = weighing_lead_from_rows(rows, beat_conviction=58, skip_netuid=13)
    assert lead is not None
    assert lead["netuid"] == 25


def test_weighing_lead_prefers_board_order_on_conviction_tie():
    """Ties break by shaped board order — not netuid."""
    from internal.simivision.weighing_room import weighing_lead_from_rows

    lead_first = weighing_lead_from_rows(
        [
            {"netuid": 71, "conviction": 89, "proximity": 69, "judge_long": True},
            {"netuid": 25, "conviction": 89, "proximity": 69, "judge_long": True},
        ],
        beat_conviction=58,
    )
    assert lead_first is not None
    assert lead_first["netuid"] == 71

    lead_second = weighing_lead_from_rows(
        [
            {"netuid": 25, "conviction": 89, "proximity": 69, "judge_long": True},
            {"netuid": 71, "conviction": 89, "proximity": 69, "judge_long": True},
        ],
        beat_conviction=58,
    )
    assert lead_second is not None
    assert lead_second["netuid"] == 25


def test_weighing_lead_prefers_judge_long_over_expert_when_other_keys_tie():
    from internal.simivision.weighing_room import weighing_lead_from_rows

    rows = [
        {"netuid": 9, "conviction": 89, "proximity": 69, "judge_long": False},
        {"netuid": 25, "conviction": 89, "proximity": 69, "judge_long": True},
    ]
    lead = weighing_lead_from_rows(rows, beat_conviction=58)
    assert lead is not None
    assert lead["netuid"] == 25


def test_weighing_lead_from_rows_skips_primary_call_bar():
    from internal.simivision.weighing_room import weighing_lead_from_rows

    rows = [
        {"netuid": 13, "conviction": 58, "primary_call": True},
        {"netuid": 25, "conviction": 89, "judge_long": True},
    ]
    lead = weighing_lead_from_rows(rows, beat_conviction=58)
    assert lead is not None
    assert lead["netuid"] == 25


def test_shape_board_hold_candidate_sets_call_bar_then_alternatives():
    daily = {
        "action": "HOLD",
        "pick": None,
        "candidate": {
            "subnet": {"netuid": 13, "name": "Data Universe"},
            "final_confidence": 0.58,
        },
    }
    top = [
        {
            "netuid": 25,
            "name": "Mainframe",
            "conviction": 89,
            "judge_long": True,
        }
    ]
    rows, meta = shape_weighing_board(top, pool_count=10, daily_pick=daily)
    assert meta["call_netuid"] == 13
    call_bar = next(r for r in rows if r.get("primary_call"))
    assert call_bar["netuid"] == 13
    mainframe = next(r for r in rows if r["netuid"] == 25)
    assert mainframe.get("primary_call") is not True
    assert mainframe["conviction"] == 89


def test_best_weighing_alternative_matches_board_lead(monkeypatch):
    from internal.simivision.weighing_room import best_weighing_alternative

    daily = {
        "action": "HOLD",
        "pick": None,
        "candidate": {
            "subnet": {"netuid": 13, "name": "Data Universe"},
            "final_confidence": 0.58,
        },
    }
    subnets = [{"netuid": 25, "name": "Mainframe"}]
    top = [
        {"netuid": 93, "name": "Bitcast", "conviction": 72, "judge_long": True},
        {"netuid": 25, "name": "Mainframe", "conviction": 89, "judge_long": True},
    ]
    monkeypatch.setattr(
        "internal.simivision.weighing_room.build_weighing_candidates_from_shortlist",
        lambda subnets, daily_pick, market_context: (top, 10),
    )
    lead = best_weighing_alternative(daily, subnets, beat_conviction=58)
    rows, _ = shape_weighing_board(top, pool_count=10, daily_pick=daily)
    board_lead = next(r for r in rows if not r.get("primary_call"))
    assert lead is not None
    assert lead["netuid"] == board_lead["netuid"] == 25


def test_spotlight_suppresses_blocked_expert_when_no_weighing_lead(monkeypatch):
    monkeypatch.setattr(
        "internal.simivision.weighing_room.build_weighing_candidates_from_shortlist",
        lambda subnets, daily_pick, market_context: ([], 0),
    )
    expert = {
        "subnet": {"netuid": 13, "name": "Data Universe"},
        "final_confidence": 0.58,
        "signal_impact": {"net_direction": "bearish", "net_predicted_pct": -0.58},
    }
    payload = {
        "action": "HOLD",
        "pick": None,
        "candidate": expert,
        "reason": "Directional conflict: council signal is bearish; no LONG published.",
    }
    out = attach_hero_spotlight_candidate(payload, [])
    assert out.get("hero_spotlight_blocked") is True
    assert "candidate" not in out
    assert out["desk_candidate"]["subnet"]["netuid"] == 13


def test_spotlight_prod_tie_uses_weighing_board_order(monkeypatch):
    """Prod-shaped tie at 89% — hero follows board row order, not netuid."""
    rows = [
        {"netuid": 13, "conviction": 58, "primary_call": True, "closest_to_call": True},
        {"netuid": 25, "conviction": 89, "judge_long": True, "proximity": 69},
        {"netuid": 71, "conviction": 89, "judge_long": True, "proximity": 69},
    ]
    payload = {
        "action": "HOLD",
        "pick": None,
        "reason": "Directional conflict: council signal is bearish; no LONG published.",
        "candidate": {
            "subnet": {"netuid": 13, "name": "Data Universe"},
            "final_confidence": 0.58,
        },
    }
    from internal.learning.dpick_spotlight import attach_hero_spotlight_from_weighing_rows

    out = attach_hero_spotlight_from_weighing_rows(payload, rows)
    assert out["hero_spotlight_source"] == "judge_long"
    assert out["candidate"]["subnet"]["netuid"] == 25


def test_enrich_web_spotlight_uses_warm_cache_and_kicks_refresh_when_cold(monkeypatch):
    from internal.learning.dpick_spotlight import enrich_daily_pick_spotlight_for_web

    payload = {
        "action": "HOLD",
        "pick": None,
        "reason": "Directional conflict: council signal is bearish; no LONG published.",
        "candidate": {
            "subnet": {"netuid": 13, "name": "Data Universe"},
            "final_confidence": 0.58,
            "signal_impact": {"net_direction": "bearish", "net_predicted_pct": -0.58},
        },
    }
    board_rows = [
        {"netuid": 13, "name": "Data Universe", "conviction": 58, "primary_call": True},
        {"netuid": 25, "name": "Mainframe", "conviction": 89, "judge_long": True},
    ]
    kicks: list[int] = []
    builds: list[int] = []

    class _FakeSrv:
        _SIMIVISION_LOCK = __import__("threading").Lock()
        _SIMIVISION_CACHE: dict = {}

        @staticmethod
        def _simivision_weighing_rows_cached(max_age_s: float = 120.0):
            return []

        @staticmethod
        def _simivision_build_inner():
            builds.append(1)
            raise AssertionError("request path must not build SimiVision")

        @staticmethod
        def _kick_simivision_background_refresh():
            kicks.append(1)

        @staticmethod
        def _subnets_for_spotlight_lite():
            raise AssertionError("request path must not hydrate subnets for spotlight")

    monkeypatch.setitem(__import__("sys").modules, "server", _FakeSrv)
    cold = enrich_daily_pick_spotlight_for_web(payload)
    assert cold.get("hero_spotlight_pending") is True
    assert "candidate" not in cold
    assert cold["desk_candidate"]["subnet"]["netuid"] == 13
    assert kicks == [1]
    assert builds == []

    class _WarmSrv(_FakeSrv):
        @staticmethod
        def _simivision_weighing_rows_cached(max_age_s: float = 120.0):
            return board_rows

    monkeypatch.setitem(__import__("sys").modules, "server", _WarmSrv)
    warm = enrich_daily_pick_spotlight_for_web(payload)
    assert warm["hero_spotlight_source"] == "judge_long"
    assert warm["candidate"]["subnet"]["netuid"] == 25
    assert warm["desk_candidate"]["subnet"]["netuid"] == 13


def test_enrich_web_spotlight_blocks_when_warm_cache_has_no_lead(monkeypatch):
    from internal.learning.dpick_spotlight import enrich_daily_pick_spotlight_for_web
    from internal.preview.tribunal_hero import subnet_label

    payload = {
        "action": "HOLD",
        "pick": None,
        "reason": "Directional conflict: council signal is bearish; no LONG published.",
        "candidate": {
            "subnet": {"netuid": 13, "name": "Data Universe"},
            "final_confidence": 0.58,
        },
    }

    class _WarmNoLead:
        @staticmethod
        def _simivision_weighing_rows_cached(max_age_s: float = 120.0):
            return [{"netuid": 13, "conviction": 58, "primary_call": True}]

        @staticmethod
        def _kick_simivision_background_refresh():
            raise AssertionError("warm cache must not kick a rebuild")

        @staticmethod
        def _simivision_build_inner():
            raise AssertionError("must not score")

    monkeypatch.setitem(__import__("sys").modules, "server", _WarmNoLead)
    out = enrich_daily_pick_spotlight_for_web(payload)
    assert out.get("hero_spotlight_blocked") is True
    assert "candidate" not in out
    assert subnet_label(out) == "Council held"
