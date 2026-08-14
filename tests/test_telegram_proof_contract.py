"""Task 5 — trusted Telegram caller proof contract.

Covers: timeframe boundaries, identity fallbacks, minimum-evidence gating,
hit/miss/neutral mapping, pending calls, and empty archives, at the shared
classifier (internal/message_intel/proof), the rollup layer, and the API.

The single source of truth is internal/message_intel/proof.classify_call —
leaderboard totals, proof bands and receipt cards must never disagree with it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from server import app


@pytest.fixture
def intel_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "message_intel.db")
    monkeypatch.setenv("MESSAGE_INTEL_DB", db_path)
    from internal.message_intel import store

    store.reset_db_cache()
    yield store.get_db(db_path)


@pytest.fixture
def client(intel_db):
    with TestClient(app) as c:
        yield c


def _seed(db, *, author_name="Nick", author_username="nick_tg", author_id=None,
          direction="up", conviction=72.0, outcome=None, pump_pct=None,
          price_24h=None, netuid=7, days_ago=0):
    timestamp = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    mid, _ = db.save_message({
        "source": "telegram",
        "group_name": "OfficialSubnetSummer",
        "author_name": author_name,
        "author_username": author_username,
        "author_id": author_id,
        "content": f"SN{netuid} call from {author_name}",
        "timestamp": timestamp,
    })
    db.save_analysis(mid, {"sentiment": "bullish", "entities": {"subnets": [netuid]}})
    db.save_verdict(mid, {
        "verdict": "bullish" if direction == "up" else "bearish",
        "conviction": conviction,
        "predicted_direction": direction,
    })
    db.save_price_snapshot(mid, 1.0, netuid=netuid)
    if outcome is not None:
        fields = {"outcome": outcome, "price_1h": 1.01}
        if pump_pct is not None:
            fields["pump_pct_max"] = pump_pct
        if price_24h is not None:
            fields["price_24h"] = price_24h
        db.save_price_outcome(mid, fields)
    return mid


# ── Classifier contract ────────────────────────────────────────────────────

def test_up_hit_miss_neutral_mapping(intel_db):
    from internal.message_intel.proof import classify_call
    hit = classify_call({"source": "telegram", "predicted_direction": "up",
                         "conviction": 70, "tao_usd_price": 1.0, "outcome": "pump",
                         "pump_pct_max": 4.2})
    assert hit["resolved"] is True and hit["evaluation"] == "resolved"
    assert hit["status"] == "hit"
    assert hit["direction"] == "up"

    miss = classify_call({"source": "telegram", "predicted_direction": "up",
                          "conviction": 70, "tao_usd_price": 1.0, "outcome": "dump",
                          "pump_pct_max": -4.0})
    assert miss["status"] == "miss"

    neutral = classify_call({"source": "telegram", "predicted_direction": "up",
                             "conviction": 70, "tao_usd_price": 1.0, "outcome": "stable"})
    assert neutral["status"] == "neutral"

    # up call where a large transient pump confirms even with no explicit outcome pump
    transient = classify_call({"source": "telegram", "predicted_direction": "up",
                               "conviction": 70, "tao_usd_price": 1.0, "outcome": "stable",
                               "pump_pct_max": 2.5})
    assert transient["status"] == "hit"


def test_down_hit_miss_mapping(intel_db):
    from internal.message_intel.proof import classify_call
    hit = classify_call({"source": "telegram", "predicted_direction": "down",
                         "conviction": 70, "tao_usd_price": 1.0, "outcome": "dump"})
    assert hit["status"] == "hit"
    miss = classify_call({"source": "telegram", "predicted_direction": "down",
                          "conviction": 70, "tao_usd_price": 1.0, "outcome": "mild_pump"})
    assert miss["status"] == "miss"


def test_flat_direction_uses_stable(intel_db):
    from internal.message_intel.proof import classify_call
    hit = classify_call({"source": "telegram", "predicted_direction": "sideways",
                         "conviction": 70, "tao_usd_price": 1.0, "outcome": "stable"})
    assert hit["status"] == "hit"
    miss = classify_call({"source": "telegram", "predicted_direction": "flat",
                          "conviction": 70, "tao_usd_price": 1.0, "outcome": "pump"})
    assert miss["status"] == "miss"


def test_price_basis_requires_subnet_or_explicit_tao():
    from internal.message_intel.proof import classify_call

    subnet = classify_call(
        {
            "source": "telegram",
            "predicted_direction": "up",
            "conviction": 70,
            "tao_usd_price": 1.0,
            "netuid": 7,
            "outcome": "pump",
        }
    )
    assert subnet["eligible"] is True
    assert subnet["price_basis"] == "subnet"
    assert subnet["subnet_name"] == "SN7"

    tao = classify_call(
        {
            "source": "telegram",
            "predicted_direction": "up",
            "conviction": 70,
            "tao_usd_price": 1.0,
            "content": "TAO looks strong",
            "outcome": "pump",
        }
    )
    assert tao["eligible"] is True
    assert tao["price_basis"] == "tao"
    assert tao["subnet_name"] is None

    chatter = classify_call(
        {
            "source": "telegram",
            "predicted_direction": "flat",
            "conviction": 70,
            "tao_usd_price": 1.0,
            "content": "Robotics along",
            "outcome": "stable",
        }
    )
    assert chatter["eligible"] is False
    assert chatter["price_basis"] is None


def test_pending_call_not_counted(intel_db):
    from internal.message_intel.proof import classify_call
    pending = classify_call({"source": "telegram", "predicted_direction": "up",
                             "conviction": 70, "tao_usd_price": 1.0, "outcome": None})
    assert pending["eligible"] is True
    assert pending["resolved"] is False
    assert pending["evaluation"] == "pending"
    assert pending["status"] == "pending"


def test_unqualified_chatter_not_a_prediction(intel_db):
    from internal.message_intel.proof import classify_call
    # no direction → not eligible
    no_dir = classify_call({"source": "telegram", "conviction": 70,
                            "tao_usd_price": 1.0, "outcome": "pump"})
    assert no_dir["eligible"] is False and no_dir["evaluation"] == "unqualified"
    # low conviction → not eligible
    low_conv = classify_call({"source": "telegram", "predicted_direction": "up",
                              "conviction": 40, "tao_usd_price": 1.0, "outcome": "pump"})
    assert low_conv["eligible"] is False


def test_direction_resolution_mirrors_locked_rule(intel_db):
    """Conflicting verdict / predicted_direction must resolve like the locked rule:
    bull verdict OR up direction → up; bear verdict OR down direction → down."""
    from internal.message_intel.proof import resolve_direction
    # Locked rule checks the up branch FIRST: bull verdict OR up direction → up,
    # then bear verdict OR down direction → down (self_learning._is_correct_prediction).
    assert resolve_direction("bullish", "down") == "up"     # bull verdict → up branch
    assert resolve_direction("neutral", "up") == "up"        # up direction → up branch
    assert resolve_direction("bearish", "up") == "up"        # up direction still → up branch
    assert resolve_direction("bearish", "down") == "down"    # bear → down branch
    assert resolve_direction("neutral", "down") == "down"    # down direction → down branch
    assert resolve_direction("bearish", "down") == "down"
    assert resolve_direction("bullish", "up") == "up"
    assert resolve_direction("neutral", "sideways") == "flat"
    assert resolve_direction(None, None) is None             # no signal → chatter


def test_classifier_parity_with_locked_rule(intel_db):
    """For every eligible+resolved call, status == "hit" iff the locked
    _is_correct_prediction returns True — including conflict rows."""
    from internal.message_intel.proof import classify_call, is_correct
    verdicts = ("bullish", "bearish")
    dirs = ("up", "down")
    outcomes = ("pump", "mild_pump", "dump", "mild_dump", "stable")
    pcts = (None, 1.0, 2.5, 4.5)
    cases = 0
    for verdict in verdicts:
        for d in dirs:
            for outcome in outcomes:
                for pct in pcts:
                    row = {"source": "telegram", "verdict": verdict,
                           "predicted_direction": d, "conviction": 70,
                           "tao_usd_price": 1.0, "outcome": outcome,
                           "pump_pct_max": pct}
                    proof = classify_call(row)
                    assert proof["eligible"] and proof["resolved"]
                    correct = is_correct(proof["direction"], outcome, pct)
                    assert (proof["status"] == "hit") is correct, (
                        f"parity broke verdict={verdict} dir={d} "
                        f"outcome={outcome} pct={pct}: {proof['status']} vs {correct}"
                    )
                    cases += 1
    # flat calls under locked rule: hit iff outcome == stable
    for outcome in outcomes:
        row = {"source": "telegram", "verdict": "neutral",
               "predicted_direction": "sideways", "conviction": 70,
               "tao_usd_price": 1.0, "outcome": outcome}
        proof = classify_call(row)
        assert proof["eligible"] and proof["resolved"]
        correct = outcome == "stable"
        assert (proof["status"] == "hit") is correct
    assert cases > 0


def test_stable_author_identity_fallbacks(intel_db):
    from internal.message_intel.proof import stable_author_id
    assert stable_author_id({"author_id": "12345", "author_username": "nick",
                             "author_name": "Nick"}) == "id:12345"
    assert stable_author_id({"author_username": "nick_tg", "author_name": "Nick"}) == "u:nick_tg"
    assert stable_author_id({"author_name": "Nick"}) == "n:Nick"
    assert stable_author_id({}) == "unknown"
    # display-name collisions must not merge distinct real identities
    assert (stable_author_id({"author_id": "1", "author_name": "Nick"})
            != stable_author_id({"author_id": "2", "author_name": "Nick"}))


# ── Rollup layer ───────────────────────────────────────────────────────────

def test_leaderboard_gating_and_accuracy(intel_db):
    from internal.message_intel.rollup import build_telegram_caller_leaderboard
    # under minimum sample → provisional (not qualified)
    _seed(intel_db, outcome="pump")   # 1 hit
    board = build_telegram_caller_leaderboard(days=30, db=intel_db)
    assert board["callers"] and board["callers"][0]["qualified"] is False
    # single resolved hit with size 1 → accuracy 100 but not ready
    assert board["callers"][0]["accuracy"] == 100.0
    # add 4 more so sample_size 5 qualifies
    for _ in range(4):
        _seed(intel_db, outcome="pump")
    board = build_telegram_caller_leaderboard(days=30, db=intel_db)
    top = board["callers"][0]
    assert top["qualified"] is True
    assert top["sample_size"] == 5
    assert top["hits"] == 5 and top["misses"] == 0 and top["neutral"] == 0


def test_leaderboard_window_boundaries(intel_db):
    from internal.message_intel.rollup import build_telegram_caller_leaderboard
    # one old hit outside 7d, a fresh miss inside 7d
    _seed(intel_db, outcome="pump", days_ago=20)
    _seed(intel_db, outcome="dump", days_ago=0)
    board7 = build_telegram_caller_leaderboard(days=7, db=intel_db)
    # old pump excluded from 7d, so only the fresh dump counts
    assert board7["callers"][0]["sample_size"] == 1
    assert board7["callers"][0]["misses"] == 1
    board90 = build_telegram_caller_leaderboard(days=90, db=intel_db)
    assert board90["callers"][0]["sample_size"] == 2


def test_receipts_and_leaderboard_agree_in_hit_miss(intel_db):
    from internal.message_intel.rollup import (
        build_telegram_caller_leaderboard, list_telegram_caller_receipts,
    )
    _seed(intel_db, outcome="pump")
    _seed(intel_db, outcome="dump")
    _seed(intel_db, outcome="middle")  # unrecognised outcome → neutral on up
    board = build_telegram_caller_leaderboard(days=30, db=intel_db)
    top = board["callers"][0]
    assert (top["hits"], top["misses"], top["neutral"]) == (1, 1, 1)
    receipts = list_telegram_caller_receipts(author_id=top["author_id"], days=30, db=intel_db)
    statuses = sorted(r["proof"]["status"] for r in receipts["receipts"])
    assert statuses == ["hit", "miss", "neutral"]
    assert receipts["total"] == 3


def test_pending_calls_excluded_from_receipts(intel_db):
    from internal.message_intel.rollup import (
        build_telegram_caller_leaderboard, list_telegram_caller_receipts,
    )
    _seed(intel_db, direction="down", outcome=None)  # pending, no outcome
    board = build_telegram_caller_leaderboard(days=30, db=intel_db)
    assert board["empty"] is True
    receipts = list_telegram_caller_receipts(author_id="id:none", days=30, db=intel_db)
    assert receipts["empty"] is True


def test_empty_archives(intel_db):
    from internal.message_intel.rollup import (
        build_telegram_caller_leaderboard, build_telegram_proof_band,
    )
    board = build_telegram_caller_leaderboard(days=30, db=intel_db)
    assert board["empty"] is True and board["callers"] == []
    band = build_telegram_proof_band(db=intel_db)
    assert band["graded"] == 0 and band["hit_rate"] is None and band["ready"] is False


# ── API surface ────────────────────────────────────────────────────────────

def test_callers_api_days_validation(client, intel_db):
    _seed(intel_db, outcome="pump")
    ok = client.get("/api/message-intel/callers?days=30").json()
    assert ok["status"] == "success" and ok["count"] >= 1
    res = client.get("/api/message-intel/callers?days=45").json()
    assert res["status"] == "error" and res["callers"] == []


def test_callers_api_honest_empty(client, intel_db):
    body = client.get("/api/message-intel/callers?days=30").json()
    assert body["status"] == "success"
    assert body["empty"] is True and body["callers"] == []


def test_caller_receipts_api(client, intel_db):
    from internal.message_intel.rollup import build_telegram_caller_leaderboard
    _seed(intel_db, outcome="pump", author_username="nick_tg")
    board = build_telegram_caller_leaderboard(days=30, db=intel_db)
    aid = board["callers"][0]["author_id"]
    body = client.get(f"/api/message-intel/callers/{aid}/receipts?days=30").json()
    assert body["status"] == "success"
    assert body["total"] == 1
    rec = body["receipts"][0]
    assert rec["proof"]["status"] == "hit"
    # proof object must not leak internal DB fields
    assert "conviction" not in rec["proof"] and "tao_usd_price" not in rec["proof"]


def test_detail_graded_flag(client, intel_db):
    _seed(intel_db, outcome="pump")
    body = client.get("/api/message-intel").json()
    assert body["status"] == "success"
    msg = next((m for m in body["messages"] if m.get("proof")), None)
    assert msg is not None
    detail = client.get(f"/api/message-intel/detail/{msg['id']}").json()
    assert detail["detail"]["graded"] is True
    assert detail["detail"]["proof"]["evaluation"] == "resolved"


def test_live_feed_resolved_proof_pill(client, intel_db):
    """A resolved qualifying call must surface its hit/miss/neutral grade inline
    in the live feed list — the primary user-visible proof card."""

    def _seed_with(dir, outcome, *, author="Nick", uname="nick_tg", netuid=7):
        mid, _ = intel_db.save_message({
            "source": "telegram", "group_name": "OfficialSubnetSummer",
            "author_name": author, "author_username": uname,
            "content": f"Live feed {dir}/{outcome} call",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        intel_db.save_analysis(mid, {"sentiment": "bullish",
                                     "entities": {"subnets": [netuid]}})
        intel_db.save_verdict(mid, {"verdict": "bullish" if dir == "up" else "bearish",
                                    "conviction": 72.0, "predicted_direction": dir})
        intel_db.save_price_snapshot(mid, 1.0, netuid=netuid)
        intel_db.save_price_outcome(mid, {"price_1h": 1.05, "price_24h": 1.05,
                                          "outcome": outcome, "pump_pct_max": 5.0})
        return mid

    # one hit, one miss, one still-pending (no outcome)
    _seed_with("up", "pump")
    _seed_with("down", "mild_pump")
    mid_pending, _ = intel_db.save_message({
        "source": "telegram", "group_name": "OfficialSubnetSummer",
        "author_name": "Nick", "author_username": "nick_tg",
        "content": "Pending live call — no price outcome yet",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    intel_db.save_analysis(mid_pending, {"sentiment": "bullish",
                                         "entities": {"subnets": [7]}})
    intel_db.save_verdict(mid_pending, {"verdict": "bullish", "conviction": 72.0,
                                        "predicted_direction": "up"})
    intel_db.save_price_snapshot(mid_pending, 1.0, netuid=7)

    body = client.get("/api/message-intel?limit=10").json()
    assert body["status"] == "success"
    by_id = {m["id"]: m for m in body["messages"]}
    assert len(by_id) == 3

    statuses = {m["proof"]["status"] for m in by_id.values() if m.get("proof")}
    # resolved calls must be graded inline; the pending one must stay pending
    assert statuses == {"hit", "miss", "pending"}
    for m in by_id.values():
        proof = m.get("proof") or {}
        if proof.get("status") == "hit":
            assert proof["evaluation"] == "resolved" and proof["move_pct"] is not None
        elif proof.get("status") == "miss":
            assert proof["evaluation"] == "resolved"
        elif proof.get("status") == "pending":
            assert proof["eligible"] is True and proof["evaluation"] == "pending"
