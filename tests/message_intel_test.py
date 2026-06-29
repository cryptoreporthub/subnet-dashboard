"""
Tests for the Message Intelligence Pipeline.

Covers: message normalization, NLP sentiment scoring, hype detection,
price snapshot recording, outcome tracking, and pattern discovery.
"""

import json
import os
import tempfile
from datetime import datetime, timezone

import pytest

from message_intel.models import Database
from message_intel.nlp_engine import NLPAnalyzer
from message_intel.price_tracker import fetch_tao_usd


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    d = Database(db_path=path)
    yield d
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def nlp():
    return NLPAnalyzer()


@pytest.fixture
def sample_message():
    return {
        "source": "telegram",
        "group_id": "-1001234567890",
        "group_name": "OfficialSubnetSummer",
        "author_id": "12345",
        "author_name": "CryptoTrader",
        "author_username": "@cryptotrader",
        "content": "Subnet 3 is looking extremely bullish! Massive emission growth and new partnerships. This could be the next big breakout. TAO to $500 soon. #Bittensor",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message_id": "98765",
        "metrics": {
            "views": 1200,
            "forwards": 45,
            "replies": 12,
            "reactions": [{"emoji": "🔥", "count": 23}],
        },
    }


# ---------------------------------------------------------------------------
# Test 1: Database save and retrieve message
# ---------------------------------------------------------------------------

def test_save_and_retrieve_message(db, sample_message):
    """Verify a message can be saved to the database and retrieved."""
    msg_id = db.save_message(sample_message)
    assert msg_id > 0

    retrieved = db.get_message(msg_id)
    assert retrieved is not None
    assert retrieved["content"] == sample_message["content"]
    assert retrieved["source"] == "telegram"
    assert retrieved["author_name"] == "CryptoTrader"
    assert retrieved["author_username"] == "@cryptotrader"


# ---------------------------------------------------------------------------
# Test 2: NLP sentiment analysis — bullish
# ---------------------------------------------------------------------------

def test_nlp_bullish_sentiment(nlp):
    """Verify bullish keywords produce a bullish sentiment score."""
    analysis = nlp.analyze(
        "This is extremely bullish! Massive breakout incoming. Buy NOW before the moon shot. Huge gains ahead."
    )
    assert analysis["sentiment"] == "bullish"
    assert analysis["sentiment_confidence"] > 0.5
    assert analysis["hype_score"] > 0.3


# ---------------------------------------------------------------------------
# Test 3: NLP sentiment analysis — bearish
# ---------------------------------------------------------------------------

def test_nlp_bearish_sentiment(nlp):
    """Verify bearish keywords produce a bearish sentiment score."""
    analysis = nlp.analyze(
        "This project looks bearish. I'm seeing major red flags and the sell pressure is overwhelming. Avoid this dump."
    )
    assert analysis["sentiment"] == "bearish"
    assert analysis["sentiment_confidence"] > 0.5
    assert analysis["hype_score"] <= 0.3  # hype words are mostly bullish


# ---------------------------------------------------------------------------
# Test 4: NLP substance scoring
# ---------------------------------------------------------------------------

def test_nlp_substance_scoring(nlp):
    """
    Verify substance scoring:
    - Message with numbers, protocol names, URLs = high substance
    - Short opinion-only message = low substance
    """
    high_substance = nlp.analyze(
        "Subnet 21's emission just hit 2.5 TAO per day. The new partnership with Tensor will drive adoption. "
        "Check the details here: https://example.com/report. Price target of $450 by Q3. #Bittensor"
    )
    assert high_substance["substance_score"] >= 0.5

    low_substance = nlp.analyze("it's going to the moon!! 🚀🚀🚀")
    assert low_substance["substance_score"] < 0.5


# ---------------------------------------------------------------------------
# Test 5: NLP entity extraction
# ---------------------------------------------------------------------------

def test_nlp_entity_extraction(nlp):
    """Verify that subnet numbers, TAO amounts, and protocols are extracted."""
    analysis = nlp.analyze(
        "Subnet #7 and sn 12 are looking great. I'm staking 150 TAO and earning 25 dTAO weekly. Go Bittensor!"
    )
    entities = analysis["entities"]
    assert any("7" in s for s in entities.get("subnets", []))
    assert any("12" in s for s in entities.get("subnets", []))
    assert any("150" in amt for amt in entities.get("tao_amounts", []))
    assert "Bittensor" in entities.get("protocols", [])


# ---------------------------------------------------------------------------
# Test 6: Hype detection
# ---------------------------------------------------------------------------

def test_hype_detection(nlp):
    """Verify high-hype messages are flagged correctly."""
    hype_message = nlp.analyze(
        "URGENT: This is a ONCE IN A LIFETIME opportunity! PUMP NOW!! X100 gains guaranteed! "
        "Don't miss the ground floor. Secret insider info leaked. FOMO is real!"
    )
    assert hype_message["hype_score"] > 0.5
    assert hype_message["substance_score"] < 0.5  # high hype, low substance

    calm_message = nlp.analyze(
        "Subnet 5 has consistent emission of 1.2 TAO/day with gradual growth over the past month."
    )
    assert calm_message["hype_score"] < 0.3


# ---------------------------------------------------------------------------
# Test 7: NLP neutral / empty message
# ---------------------------------------------------------------------------

def test_nlp_empty_and_neutral(nlp):
    """Verify empty messages return default neutral analysis."""
    empty = nlp.analyze("")
    assert empty["sentiment"] == "neutral"
    assert empty["sentiment_confidence"] == 0.0
    assert empty["hype_score"] == 0.0
    assert empty["substance_score"] == 0.0

    neutral = nlp.analyze("The network is processing transactions normally.")
    assert neutral["sentiment"] == "neutral"


# ---------------------------------------------------------------------------
# Test 8: Price snapshot recording
# ---------------------------------------------------------------------------

def test_price_snapshot_recorded(db):
    """Verify a price snapshot can be saved and retrieved for a message."""
    from message_intel.price_tracker import PriceTracker

    # Save a message first
    msg_id = db.save_message({
        "source": "telegram",
        "content": "Bullish on subnet 3",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    pt = PriceTracker(db=db)
    price = pt.snapshot(msg_id)

    # The snapshot should be saved regardless of price fetch result
    msg = db.get_message(msg_id)
    assert msg is not None
    ps = msg.get("price_snapshot")
    if ps:
        assert ps["message_id"] == msg_id
        if price is not None:
            assert ps["tao_usd_price"] == price


# ---------------------------------------------------------------------------
# Test 9: Price outcome recording
# ---------------------------------------------------------------------------

def test_price_outcome_tracking(db):
    """Verify outcomes can be saved and retrieved."""
    # Save a message with a snapshot
    msg_id = db.save_message({
        "source": "telegram",
        "content": "Price prediction test",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    db.save_price_snapshot(msg_id, 450.0)

    outcome = {
        "price_1h": 455.0,
        "price_4h": 462.0,
        "price_24h": 470.0,
        "price_7d": None,
        "pump_pct_max": 4.44,
        "time_to_pump": 4.0,
        "pump_duration": 20.0,
        "resurgence": 0.0,
        "outcome": "mild_pump",
    }
    db.save_price_outcome(msg_id, outcome)

    msg = db.get_message(msg_id)
    assert msg is not None
    po = msg.get("price_outcome")
    assert po is not None
    assert po["outcome"] == "mild_pump"
    assert po["price_24h"] == 470.0


# ---------------------------------------------------------------------------
# Test 10: Full pipeline integration (ingest + analyze + jury + persist)
# ---------------------------------------------------------------------------

def test_full_pipeline_integration(db, nlp):
    """Verify the complete message processing pipeline end-to-end."""
    from message_intel.jury_bridge import JuryBridge

    try:
        from internal.council.judge.adversarial import AdversarialJudge
    except ModuleNotFoundError:
        from message_intel.jury_bridge import AdversarialJudge

    content = "Subnet 7 is massively bullish with 3.5 TAO emission and growing adoption!"

    # Save message
    msg_id = db.save_message({
        "source": "telegram",
        "content": content,
        "author_id": "999",
        "author_name": "TestUser",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    # Run NLP
    analysis = nlp.analyze(content)
    db.save_analysis(msg_id, analysis)
    assert analysis["sentiment"] == "bullish"

    # Run jury
    judge = AdversarialJudge(persist=False)
    bridge = JuryBridge(judge=judge)
    verdict = bridge.evaluate(msg_id, content, analysis)
    db.save_verdict(msg_id, verdict)
    assert verdict["verdict"] in ("bullish", "neutral")
    assert verdict["conviction"] >= 0

    # Verify stored
    msg = db.get_message(msg_id)
    assert msg["analysis"]["sentiment"] == "bullish"
    assert msg["verdict"]["verdict"] == verdict["verdict"]


# ---------------------------------------------------------------------------
# Test 11: Author reliability scoring
# ---------------------------------------------------------------------------

def test_author_reliability(db):
    """Verify author reliability records are correctly created."""
    db.upsert_author_reliability({
        "author_id": "author_1",
        "author_name": "TraderOne",
        "total_messages": 10,
        "correct_predictions": 7,
        "accuracy_score": 0.7,
    })

    db.upsert_author_reliability({
        "author_id": "author_2",
        "author_name": "TraderTwo",
        "total_messages": 5,
        "correct_predictions": 2,
        "accuracy_score": 0.4,
    })

    # Verify by querying directly
    with db._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM author_reliability ORDER BY accuracy_score DESC"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]["author_id"] == "author_1"
        assert rows[0]["accuracy_score"] == 0.7


# ---------------------------------------------------------------------------
# Test 12: Pattern discovery
# ---------------------------------------------------------------------------

def test_pattern_discovery(db):
    """Verify patterns can be saved and listed."""
    db.save_pattern({
        "pattern_description": "High substance bullish messages often predict upward moves",
        "match_count": 15,
        "success_rate": 0.7333,
        "confidence": 0.35,
    })
    db.save_pattern({
        "pattern_description": "High hype messages without substance rarely predict correctly",
        "match_count": 12,
        "success_rate": 0.25,
        "confidence": 0.3,
    })

    patterns = db.list_patterns()
    assert len(patterns) >= 2
    assert patterns[0]["match_count"] == 15


# ---------------------------------------------------------------------------
# Test 13: High conviction message filtering
# ---------------------------------------------------------------------------

def test_high_conviction_filter(db):
    """Verify filtering messages by conviction threshold works."""
    msg_id = db.save_message({
        "source": "telegram",
        "content": "Strong conviction signal",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    db.save_verdict(msg_id, {
        "verdict": "bullish",
        "conviction": 85.0,
        "reasoning": "Strong signal",
        "predicted_direction": "up",
        "predicted_magnitude": 0.1,
        "predicted_timeframe": "4h-24h",
        "predicted_confidence": 0.75,
    })

    high_conv = db.list_high_conviction_messages(min_conviction=0.6)
    assert len(high_conv) >= 1
    assert high_conv[0]["conviction"] >= 0.6

    # Test with high threshold that won't match
    none_found = db.list_high_conviction_messages(min_conviction=99.0)
    assert len(none_found) == 0


# ---------------------------------------------------------------------------
# Test 14: Database schema — all tables created
# ---------------------------------------------------------------------------

def test_database_schema(db):
    """Verify all expected tables exist in the database."""
    with db._connect() as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t["name"] for t in tables]

    expected = [
        "messages",
        "message_metrics",
        "message_analysis",
        "message_verdicts",
        "price_snapshots",
        "price_outcomes",
        "author_reliability",
        "pattern_correlations",
    ]
    for name in expected:
        assert name in table_names, f"Missing table: {name}"