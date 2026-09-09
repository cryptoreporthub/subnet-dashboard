from message_intel.nlp_engine import NLPAnalyzer


def test_negated_bullish_is_not_bullish():
    result = NLPAnalyzer().analyze("SN11 is not bullish")
    assert result["sentiment"] != "bullish"


def test_deceptive_language_is_bearish():
    result = NLPAnalyzer().analyze("SN11 is a scam")
    assert result["sentiment"] == "bearish"


def test_contracted_negation_blocks_pump():
    result = NLPAnalyzer().analyze("SN11 won't pump")
    assert result["sentiment"] != "bullish"


def test_inflected_dump_matches_bearish_root():
    result = NLPAnalyzer().analyze("SN62 is dumping imo")
    assert result["sentiment"] == "bearish"


def test_positive_buying_message_stays_bullish():
    result = NLPAnalyzer().analyze("I'm buying SN92")
    assert result["sentiment"] == "bullish"
