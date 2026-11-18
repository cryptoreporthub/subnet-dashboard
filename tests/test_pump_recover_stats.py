"""Pump lead recovery must store the same stats the resolver computes.

Recovery writes the ledger through merge_ledger_changes. Without the resolver's stats
function, the default recompute produced a different stats block than the resolver writes,
so the stored counts disagreed with the rows after a recovery.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from internal.council import price_reference, resolver
from internal.learning import pump_lead_recover


def test_pump_recovery_stores_resolver_stats(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    past = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat().replace("+00:00", "Z")
    path = tmp_path / "predictions.json"
    path.write_text(json.dumps({
        "predictions": [{
            "id": "p1", "netuid": 5, "created_at": past, "resolve_at": past,
            "horizon_type": "hour", "status": "pending", "pick_source": "pump_combined_exp",
            "reference_price": 1.0, "predicted_pct": 2.0,
        }],
        "resolved": [
            {"id": "c1", "netuid": 7, "created_at": past, "horizon_type": "hour",
             "status": "resolved", "outcome": "hit", "correct": True, "pick_source": "council"},
            {"id": "c2", "netuid": 8, "created_at": past, "horizon_type": "hour",
             "status": "resolved", "outcome": "expired", "correct": None, "pick_source": "council"},
        ],
        "stats": {},
    }))

    def grade(pred, now=None, cache=None, hydrate=False):
        out = dict(pred)
        out.update(status="resolved", outcome="hit", correct=True, actual_pct=3.0,
                   resolved_price=1.03, resolved_at=past)
        return out

    monkeypatch.setattr(pump_lead_recover, "grade_pump_lead_at_resolve_candle", grade)
    monkeypatch.setattr(pump_lead_recover, "hydrate_overdue_pump_lead_netuids",
                        lambda *a, **k: {"attempted": 0, "ready": 0, "fetched": 0, "netuids": []})
    monkeypatch.setattr(price_reference, "_load_cache", lambda *a, **k: {})
    monkeypatch.setattr(pump_lead_recover, "update_pump_horizon_outcomes", lambda *a, **k: 0)

    out = pump_lead_recover.recover_overdue_pump_leads(path=str(path), hydrate=False)
    assert out.get("ok") is not False, out

    final = json.loads(path.read_text())
    assert final["stats"], "recovery wrote an empty stats block"
    assert final["stats"] == resolver._compute_stats(final)
