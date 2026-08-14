"""§30 Living Brain closure tests."""

from pathlib import Path
from unittest.mock import patch

from internal.council.memory_scoring import (
    disposition_score_adjustment,
    scenario_outcome_adjustment,
)
from internal.council.weights import load_weights, nudge_expert, nudge_signal_weight, save_weights


def test_living_focus_reads_trail_evidence_schema():
    js = Path("static/js/living_focus.js").read_text(encoding="utf-8")
    assert "function trailEvidence" in js
    assert "function pickLearnEvent" in js
    assert "function focusActionBadge" in js
    assert "Open subnet" in js
    # weight bar: bare --pct number (CSS multiplies by 1%)
    assert "style=\"--pct:' + pct + '\"" in js or 'style="--pct:\' + pct + \'"' in js
    assert "--pct:' + pct + '%" not in js


def test_b0_a_living_focus_four_beat_present():
    html = Path("templates/partials/premium/living_focus.html").read_text(encoding="utf-8")
    assert "section-living-focus" in html
    assert "Focus · Contest · Prove it · Watch us update" in html
    assert "living-focus-weights" in html
    assert "Focus opens when judges score this subnet" in html

    js = Path("static/js/living_focus.js").read_text(encoding="utf-8")
    assert "renderJudgeLanes" in js
    assert "Judges (Oracle · Echo · Pulse)" in js
    assert "showWeightLean" in js
    assert "living-focus-weights" in js


    from fastapi.testclient import TestClient
    from server import app

    client = TestClient(app)
    res = client.get("/api/calibration/status")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data.get("weights"), dict)
    assert data["weights"]


def test_living_focus_paints_judges_before_optional_enrichment():
    js = Path("static/js/living_focus.js").read_text(encoding="utf-8")
    assert "var immediateFocus" in js
    assert "return fetchJson('/api/judges/' + focusNetuid, 15000)" in js
    assert "optional judge enrichment failed" in js


def test_trail_matches_focus_netuid_logic():
    """LB-2: null netuid must not match unless payload carries focus netuid."""
    focus = 42

    def matches(ev):
        if not ev:
            return False
        if ev.get("netuid") is not None and int(ev["netuid"]) != focus:
            return False
        if ev.get("event_type") in ("prediction_resolved", "weight_change"):
            if ev.get("netuid") is None:
                pl = ev.get("payload") or ev
                if not pl or pl.get("netuid") is None or int(pl["netuid"]) != focus:
                    return False
            return True
        payload = ev.get("payload") or ev
        return bool(payload.get("netuid") is not None and int(payload["netuid"]) == focus)

    assert not matches({"event_type": "weight_change", "netuid": None})
    assert matches(
        {
            "event_type": "weight_change",
            "netuid": 42,
            "payload": {"before": 1.0, "after": 1.05},
        }
    )


def test_nudge_signal_weight_emits_trail(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    save_weights({"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}, str(soul))
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    emitted = []

    def _capture(*args, **kwargs):
        emitted.append({"args": args, "kwargs": kwargs})

    monkeypatch.setattr("internal.learning.trail_bus.emit_weight_change", _capture)
    after = nudge_signal_weight("hour", "rsi", True, str(soul))
    assert after is not None
    assert emitted
    assert emitted[0]["kwargs"]["reason"] == "signal_resolve"


def test_disposition_adjustment_bullish(monkeypatch):
    payload = {
        "soul_map_state": {
            "message_intel_dispositions": {
                "7": {"recommended_action": "buy", "conviction": 80},
            }
        }
    }
    from internal.council import weights as wmod

    monkeypatch.setattr(wmod, "_load_raw", lambda path=None: payload)
    adj = disposition_score_adjustment({"netuid": 7})
    assert adj > 0


def test_scenario_outcome_adjustment_neutral_without_data():
    assert scenario_outcome_adjustment({"netuid": 99}) == 0.0


def test_feedback_nudges_with_trail(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    save_weights({"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}, str(soul))
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    emitted = []
    monkeypatch.setattr(
        "internal.learning.trail_bus.emit_weight_change",
        lambda *a, **k: emitted.append(k),
    )
    from datastore.learning_engine import LearningEngine

    engine = LearningEngine(str(soul))
    out = engine.record_feedback(1, "quant", {"correct_prediction": True})
    assert out["success"] is True
    assert emitted
    assert emitted[0]["reason"] == "feedback"


def test_council_subnet_feed_returns_rows(monkeypatch):
    from internal.subnets.feed import get_council_subnet_feed

    monkeypatch.setattr(
        "internal.subnets.feed.load_subnets_source",
        lambda timeout=None: [{"netuid": 1, "name": "Alpha", "price": 1.0, "price_change_24h": 2.0, "source": "taomarketcap"}],
    )
    rows, source = get_council_subnet_feed()
    assert source == "taomarketcap"
    assert rows and rows[0]["netuid"] == 1


def test_enrich_rejects_snnone():
    from internal.subnet_names import enrich_subnet_row

    row = enrich_subnet_row({"netuid": 82, "name": "SNNone"}, use_taostats=False)
    assert row["name"] != "SNNone"
    assert row["name"]


def test_alignment_uses_nudge_expert(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    save_weights({"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}, str(soul))
    import internal.council.weights as weights_mod

    monkeypatch.setattr(weights_mod, "SOUL_MAP_PATH", str(soul))
    from internal.learning.alignment_nudge import apply_alignment_nudge

    out = apply_alignment_nudge({"alignment_score": 0.9, "status": "aligned"})
    assert out["applied"] is True
    assert load_weights(str(soul))["quant"] > 1.0


def test_self_learning_adjust_jury_uses_nudge_expert(tmp_path, monkeypatch):
    """§30-4: intel pattern path must not renormalize council weights to 1.0."""
    soul = tmp_path / "soul_map.json"
    save_weights({"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}, str(soul))
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))

    class _FakeDb:
        def list_patterns(self, limit=20):
            return [{"success_rate": 0.8, "pattern_description": "hype spike on subnet"}]

    from message_intel.self_learning import SelfLearning

    sl = SelfLearning(db=_FakeDb())
    sl.adjust_jury_weights()
    weights = load_weights(str(soul))
    total = sum(weights.values())
    assert weights["hype"] > 1.0
    assert 3.5 < total < 4.5
