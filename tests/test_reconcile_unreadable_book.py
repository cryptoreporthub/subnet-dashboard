"""An unreadable portfolio book fails the reconcile sweep, even with no picks to reconcile."""

import json

import pytest

from internal.judges import portfolios
from internal.learning import prediction_loop


def test_unreadable_book_fails_reconcile_with_no_eligible_picks(tmp_path, monkeypatch):
    ledger = tmp_path / "predictions.json"
    ledger.write_text(json.dumps({"predictions": [], "resolved": [], "stats": {}}))
    monkeypatch.setattr(
        portfolios, "observe_portfolios",
        lambda: {"kind": "unreadable", "error": "bad json", "data": {}},
    )
    with pytest.raises(portfolios.PortfolioUnreadable):
        prediction_loop.reconcile_judge_positions(predictions_path=str(ledger))
