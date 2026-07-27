"""Pick selection audit — evidence loop for nightly oracle replay."""

from __future__ import annotations

from unittest.mock import MagicMock

import internal.council.pick_selection_audit as audit
import internal.council.pick_audit_scheduler as sched


def test_classify_pass_when_primary_matches():
    oracles = {
        audit.PRIMARY_POLICY: {"pick": {"netuid": 40, "name": "Chunking", "final_confidence": 0.52}},
        audit.POLICY_FULL: {"pick": {"netuid": 78, "name": "SN78", "final_confidence": 0.57}},
    }
    row = {"action": "LONG", "pick": {"subnet": {"netuid": 40, "name": "Chunking"}}}
    verdict, category = audit.classify_miss(40, "pick", row, oracles)
    assert verdict == "PASS"
    assert category == audit._CATEGORY_PASS


def test_classify_universe_mismatch_sn78_pattern():
    """2026-07-27 prod: published 78 on full universe; scheduler oracle 40."""
    oracles = {
        audit.PRIMARY_POLICY: {
            "pick": {"netuid": 40, "name": "Chunking", "final_confidence": 0.52, "tie_break": None},
        },
        audit.POLICY_FULL: {
            "pick": {"netuid": 78, "name": "SN78", "final_confidence": 0.57, "tie_break": None},
        },
    }
    row = {
        "action": "LONG",
        "pick": {"subnet": {"netuid": 78, "name": "SN78"}, "final_confidence": 0.568},
    }
    verdict, category = audit.classify_miss(78, "pick", row, oracles)
    assert verdict == "MISS"
    assert category == audit._CATEGORY_UNIVERSE


def test_discovery_questions_universe_mismatch():
    oracles = {
        audit.PRIMARY_POLICY: {"pick": {"netuid": 40, "name": "Chunking", "final_confidence": 0.52}},
        audit.POLICY_FULL: {"pick": {"netuid": 78, "name": "SN78", "final_confidence": 0.57}},
    }
    row = {"action": "LONG", "pick": {"subnet": {"netuid": 78, "name": "SN78"}}}
    q = audit.discovery_questions(
        audit._CATEGORY_UNIVERSE, 78, row, oracles
    )
    assert "scheduler_cap_24" in q["what"] or "Chunking" in q["what"]
    assert "full" in q["why"].lower() or "cap" in q["why"].lower()
    assert q["rule"]


def test_universe_for_policy_scheduler_cap(monkeypatch):
    subnets = [{"netuid": i, "name": f"SN{i}", "marketcap_rank": i} for i in range(1, 50)]
    monkeypatch.setenv("PICK_SCHEDULER_UNIVERSE_CAP", "24")
    monkeypatch.setenv("TOP_SCORING_UNIVERSE", "40")
    monkeypatch.setenv("SCORING_CAP_MEGA_CEILING_RANK", "10")
    out = audit.universe_for_policy(subnets, audit.PRIMARY_POLICY)
    assert len(out) <= 24


def test_audit_row_miss_writes_questions(monkeypatch):
    def _fake_oracle(subnets, ctx, policy):
        picks = {
            audit.PRIMARY_POLICY: 40,
            audit.POLICY_FULL: 78,
        }
        nu = picks.get(policy, 1)
        return {
            "policy": policy,
            "universe_size": len(subnets),
            "pick": {
                "netuid": nu,
                "name": f"SN{nu}",
                "total_score": 90.0,
                "raw_confidence": 0.55,
                "final_confidence": 0.52,
                "audit_concerns": [],
                "tie_break": None,
            },
        }

    monkeypatch.setattr(audit, "oracle_for_policy", _fake_oracle)
    row = {
        "date": "2026-07-27",
        "timestamp_utc": "2026-07-27T17:24:37Z",
        "action": "LONG",
        "pick": {"subnet": {"netuid": 78, "name": "SN78"}, "score": 99},
    }
    payload = audit.audit_row(row, [{"netuid": 78}, {"netuid": 40}], {})
    assert payload["verdict"] == "MISS"
    assert payload["category"] == audit._CATEGORY_UNIVERSE
    assert payload["questions"]["what"]
    assert payload["oracles"][audit.PRIMARY_POLICY]["pick"]["netuid"] == 40


def test_run_audit_no_row(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "DAILY_PICKS_PATH", str(tmp_path / "daily_picks.json"))
    monkeypatch.setattr(audit, "PICK_AUDITS_DIR", str(tmp_path / "audits"))
    payload = audit.run_audit_for_date([], {}, "2026-07-01", save=True)
    assert payload["verdict"] == "SKIP"
    assert (tmp_path / "audits" / "2026-07-01.json").is_file()


def test_pick_audit_scheduler_disabled(monkeypatch):
    monkeypatch.setenv("PICK_AUDIT_ENABLED", "off")
    sched.stop_pick_audit_scheduler()
    out = sched.start_pick_audit_scheduler()
    assert out["started"] is False


def test_pick_audit_run_once(monkeypatch):
    sched.stop_pick_audit_scheduler()
    monkeypatch.setattr(sched, "_load_subnets_and_context", lambda: ([{"netuid": 1}], {}))
    monkeypatch.setattr(
        "internal.council.pick_selection_audit.run_audit_today",
        lambda subnets, ctx, save=True: {
            "verdict": "PASS",
            "category": "pass",
            "published_netuid": 1,
            "oracles": {"scheduler_cap_24": {"pick": {"netuid": 1}}},
            "pick_date": "2026-07-27",
        },
    )
    result = sched.PickSelectionAuditScheduler().run_once()
    assert result["ok"] is True
    assert result["verdict"] == "PASS"


def test_background_boot_wires_pick_audit():
    from pathlib import Path

    boot = Path("internal/background_boot.py").read_text(encoding="utf-8")
    assert "_start_pick_audit_scheduler" in boot
    assert "start_pick_audit_scheduler" in boot
