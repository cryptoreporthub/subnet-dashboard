"""Author reliability feedback loop — incremental DB updates + jury trust multiplier."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from internal.message_intel.jury import _build_signal, evaluate_message
from internal.message_intel.rollup import build_author_reliability_rows
from message_intel.models import Database
from message_intel.price_tracker import PriceTracker

ANALYSIS = {
    "sentiment": "bullish",
    "hype_score": 0.2,
    "substance_score": 0.8,
    "influence_score": 0.7,
}


@pytest.fixture
def intel_env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "message_intel.db")
    monkeypatch.setenv("MESSAGE_INTEL_DB", db_path)
    from internal.message_intel import store

    store.reset_db_cache()
    yield {"db_path": db_path}


def _nlp_fallback_patch():
    """Force NLP fallback so conviction = _build_signal consensus only."""
    return patch(
        "internal.council.judge.adversarial.AdversarialJudge",
        side_effect=Exception("forced NLP fallback"),
    )


def test_increment_author_reliability_fresh(intel_env):
    db = Database(intel_env["db_path"])
    row = db.increment_author_reliability("u1", "Alice", correct=True)
    assert row["total_messages"] == 1
    assert row["correct_predictions"] == 1
    assert row["accuracy_score"] == 1.0

    row2 = db.increment_author_reliability("u2", "Bob", correct=False)
    assert row2["total_messages"] == 1
    assert row2["correct_predictions"] == 0
    assert row2["accuracy_score"] == 0.0


def test_increment_author_reliability_sequential(intel_env):
    db = Database(intel_env["db_path"])
    db.increment_author_reliability("u1", "Alice", correct=True)
    db.increment_author_reliability("u1", "Alice", correct=False)
    row = db.increment_author_reliability("u1", "Alice", correct=True)
    assert row["total_messages"] == 3
    assert row["correct_predictions"] == 2
    assert row["accuracy_score"] == 0.6667


def test_get_author_reliability_unknown_returns_none(intel_env):
    db = Database(intel_env["db_path"])
    assert db.get_author_reliability("missing") is None


def test_get_author_reliability_known_returns_row(intel_env):
    db = Database(intel_env["db_path"])
    db.increment_author_reliability("u1", "Alice", correct=True)
    row = db.get_author_reliability("u1")
    assert row is not None
    assert set(row.keys()) == {
        "author_id",
        "author_name",
        "total_messages",
        "correct_predictions",
        "accuracy_score",
    }
    assert row["author_id"] == "u1"


def test_check_outcomes_increments_when_verdict_present(intel_env):
    db = Database(intel_env["db_path"])
    msg_id, _ = db.save_message(
        {
            "source": "telegram",
            "author_id": "u1",
            "author_name": "Alice",
            "content": "bullish",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    db.save_verdict(
        msg_id,
        {"verdict": "bullish", "predicted_direction": "up", "conviction": 70},
    )
    snapshot_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    with db._connect() as conn:
        conn.execute(
            """INSERT INTO price_snapshots (message_id, tao_usd_price, snapshot_timestamp)
               VALUES (?, ?, ?)""",
            (msg_id, 100.0, snapshot_ts),
        )

    tracker = PriceTracker(db=db)
    with patch("message_intel.price_tracker.fetch_tao_usd", return_value=110.0):
        tracker.check_outcomes()

    row = db.get_author_reliability("u1")
    assert row is not None
    assert row["total_messages"] == 1


def test_check_outcomes_skips_when_verdict_absent(intel_env):
    db = Database(intel_env["db_path"])
    msg_id, _ = db.save_message(
        {
            "source": "telegram",
            "author_id": "u1",
            "author_name": "Alice",
            "content": "no verdict",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    snapshot_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    with db._connect() as conn:
        conn.execute(
            """INSERT INTO price_snapshots (message_id, tao_usd_price, snapshot_timestamp)
               VALUES (?, ?, ?)""",
            (msg_id, 100.0, snapshot_ts),
        )

    tracker = PriceTracker(db=db)
    spy = MagicMock(wraps=db.increment_author_reliability)
    db.increment_author_reliability = spy
    with patch("message_intel.price_tracker.fetch_tao_usd", return_value=110.0):
        tracker.check_outcomes()

    spy.assert_not_called()


def test_evaluate_message_cold_start_identical(intel_env):
    with _nlp_fallback_patch():
        baseline = evaluate_message(1, "test", ANALYSIS)
        no_author = evaluate_message(1, "test", ANALYSIS, author_id=None)
        unknown = evaluate_message(1, "test", ANALYSIS, author_id="unknown_author")
    assert baseline["conviction"] == no_author["conviction"]
    assert baseline["conviction"] == unknown["conviction"]


def test_evaluate_message_neutral_accuracy_no_shift(intel_env):
    from internal.message_intel.store import get_db

    db = get_db()
    db.upsert_author_reliability(
        {
            "author_id": "neutral_u",
            "author_name": "Neutral",
            "total_messages": 20,
            "correct_predictions": 10,
            "accuracy_score": 0.5,
        }
    )
    with _nlp_fallback_patch():
        baseline = evaluate_message(1, "test", ANALYSIS)
        shifted = evaluate_message(1, "test", ANALYSIS, author_id="neutral_u")
    assert shifted["conviction"] == baseline["conviction"]


def test_evaluate_message_bounds_full_ramp(intel_env):
    from internal.message_intel.store import get_db

    db = get_db()
    base_conf = float(_build_signal("test", ANALYSIS)["consensus_score"])

    db.upsert_author_reliability(
        {
            "author_id": "perfect",
            "author_name": "Perfect",
            "total_messages": 20,
            "correct_predictions": 20,
            "accuracy_score": 1.0,
        }
    )
    db.upsert_author_reliability(
        {
            "author_id": "terrible",
            "author_name": "Terrible",
            "total_messages": 20,
            "correct_predictions": 0,
            "accuracy_score": 0.0,
        }
    )

    with _nlp_fallback_patch():
        high = evaluate_message(1, "test", ANALYSIS, author_id="perfect")
        low = evaluate_message(2, "test", ANALYSIS, author_id="terrible")

    expected_high = round(min(1.0, base_conf * 1.2) * 100, 2)
    expected_low = round(min(1.0, base_conf * 0.8) * 100, 2)
    assert high["conviction"] == expected_high
    assert low["conviction"] == expected_low


def test_evaluate_message_sample_damping(intel_env):
    from internal.message_intel.store import get_db

    db = get_db()
    db.upsert_author_reliability(
        {
            "author_id": "one_msg",
            "author_name": "Newbie",
            "total_messages": 1,
            "correct_predictions": 1,
            "accuracy_score": 1.0,
        }
    )
    db.upsert_author_reliability(
        {
            "author_id": "full_ramp",
            "author_name": "Veteran",
            "total_messages": 20,
            "correct_predictions": 20,
            "accuracy_score": 1.0,
        }
    )

    with _nlp_fallback_patch():
        baseline = evaluate_message(1, "test", ANALYSIS)
        damped = evaluate_message(2, "test", ANALYSIS, author_id="one_msg")
        full = evaluate_message(3, "test", ANALYSIS, author_id="full_ramp")

    delta_damped = abs(damped["conviction"] - baseline["conviction"])
    delta_full = abs(full["conviction"] - baseline["conviction"])
    assert delta_damped < delta_full


def test_write_then_read_e2e(intel_env):
    from internal.message_intel.store import get_db

    db = get_db()
    db.increment_author_reliability("e2e_u", "E2E", correct=True)
    db.increment_author_reliability("e2e_u", "E2E", correct=True)

    with _nlp_fallback_patch():
        baseline = evaluate_message(1, "test", ANALYSIS)
        trusted = evaluate_message(2, "test", ANALYSIS, author_id="e2e_u")

    assert trusted["conviction"] != baseline["conviction"]


def test_author_reliability_rows_expose_strike_rate_and_caution(intel_env):
    db = Database(intel_env["db_path"])
    db.save_message(
        {
            "source": "telegram",
            "author_id": "u1",
            "author_name": "Alice",
            "content": "one",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    with db._connect() as conn:
        conn.execute(
            """INSERT INTO price_outcomes (message_id, outcome, price_24h)
               VALUES (1, ?, ?)""",
            ("pump", 1.0),
        )
    db.upsert_author_reliability(
        {
            "author_id": "u1",
            "author_name": "Alice",
            "total_messages": 4,
            "correct_predictions": 3,
            "accuracy_score": 0.75,
        }
    )

    rows = build_author_reliability_rows(days=30, limit=8, db=db)
    assert rows
    row = rows[0]
    assert row["accuracy_pct"] == row["strike_rate_pct"]
    assert row["correct_predictions"] == 3
    assert row["total_graded_calls"] == 4
    assert row["caution"] is True
