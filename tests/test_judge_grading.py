from internal.judges.grading import judge_nudge_correct


def test_judge_nudge_correct_endorsed_hit():
    pred = {
        "direction": "up",
        "judge_scores_at_creation": {"oracle": {"score": 0.8}},
    }
    assert judge_nudge_correct(pred, "oracle", actual_pct=2.0) is True


def test_judge_nudge_correct_abstained_miss():
    pred = {
        "direction": "up",
        "judge_scores_at_creation": {"echo": {"score": 0.4}},
    }
    assert judge_nudge_correct(pred, "echo", actual_pct=-1.0) is True


def test_judge_nudge_correct_endorsed_miss():
    pred = {
        "direction": "up",
        "judge_scores_at_creation": {"pulse": {"score": 0.7}},
    }
    assert judge_nudge_correct(pred, "pulse", actual_pct=-1.0) is False


def test_judge_nudge_correct_abstained_hit():
    pred = {
        "direction": "up",
        "judge_scores_at_creation": {"echo": {"score": 0.45}},
    }
    assert judge_nudge_correct(pred, "echo", actual_pct=3.0) is False


def test_judge_nudge_correct_legacy_pnl_fallback():
    pred = {"direction": "up"}
    assert judge_nudge_correct(pred, "oracle", actual_pct=1.0, pnl_pct=2.0) is True
    assert judge_nudge_correct(pred, "oracle", actual_pct=1.0, pnl_pct=-1.0) is False
