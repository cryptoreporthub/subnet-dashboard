from __future__ import annotations

from internal.learning.evidence import evidence_population, evidence_source, stamp_evidence
from internal.learning.pump_calibration import maybe_adapt_after_resolve


def test_evidence_contract_separates_council_pump_shadow_and_archive():
    cases = [
        ({"pick_source": "council"}, "council_published", "council"),
        ({"pick_source": "pump_lead", "pump_badge": "BUILDING"}, "pump_early", "pump"),
        ({"pick_source": "pump_lead", "pump_claim": "JUST_STARTED"}, "pump_just_started", "pump"),
        ({"pick_source": "pump_combined_exp"}, "pump_combined_experimental", "pump"),
        ({"shadow": True}, "council_shadow", "shadow"),
        ({"archived": True}, "archived", "archive"),
    ]
    for row, population, source in cases:
        assert evidence_population(row) == population
        assert evidence_source(row) == source
        assert stamp_evidence(row) is True
        assert row["evidence_population"] == population
        assert row["evidence_source"] == source
        assert stamp_evidence(row) is False


def test_pump_calibration_requires_active_ledger_sample(monkeypatch, tmp_path):
    calibration_path = tmp_path / "pump_calibration.json"
    monkeypatch.setattr(
        "internal.learning.pump_calibration.load_calibration",
        lambda path=None: {
            "adapted_from_n": 0,
            "adapted_at": None,
            "lead_buy_ratio_min": 0.55,
            "lead_volume_intensity_min": 0.22,
            "phase_entry": {"STIRRING": 0.22, "ACCUMULATING": 0.42},
        },
    )
    monkeypatch.setattr(
        "internal.learning.pump_lead_stats.build_pump_desk_trust",
        lambda: {"early": {"n": 29, "hit_rate": 0.1}},
    )
    assert maybe_adapt_after_resolve(min_sample=30) is None


def test_stale_pump_calibration_provenance_does_not_block_recalibration(monkeypatch):
    saved = []
    monkeypatch.setattr(
        "internal.learning.pump_lead_stats.build_pump_desk_trust",
        lambda: {"early": {"n": 30, "hit_rate": 0.1}},
    )
    monkeypatch.setattr(
        "internal.learning.pump_calibration.load_calibration",
        lambda path=None: {
            "adapted_from_n": 49,
            "adapted_at": "2026-01-01T00:00:00Z",
            "adapted_from_fingerprint": None,
            "lead_buy_ratio_min": 0.55,
            "lead_volume_intensity_min": 0.22,
            "phase_entry": {"STIRRING": 0.22, "ACCUMULATING": 0.42},
        },
    )
    monkeypatch.setattr(
        "internal.learning.pump_calibration.save_calibration",
        lambda data, path=None: saved.append(data),
    )
    result = maybe_adapt_after_resolve(min_sample=30)
    assert result is not None
    assert saved and saved[0]["adapted_from_fingerprint"]
