"""Universe-wide forward labels: realised moves from price candles only."""

from datetime import datetime, timedelta, timezone

from internal.learning.universe_labels import (
    STATUS_NO_ENTRY,
    STATUS_NO_EXIT,
    STATUS_OK,
    closes_from_candles,
    forward_label,
    universe_labels,
)

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


def _candles(start: datetime, closes):
    return [
        {"timestamp": (start + HOUR * i).isoformat(), "close": c}
        for i, c in enumerate(closes)
    ]


def test_forward_return_uses_last_close_at_entry_and_horizon():
    closes = closes_from_candles(_candles(T0 - HOUR, [1.0, 1.1, 1.2, 1.5]))
    label = forward_label(7, closes, T0, timedelta(hours=2))
    assert label.status == STATUS_OK
    assert label.entry_close == 1.1
    assert label.exit_close == 1.5
    assert round(label.forward_return, 6) == round(1.5 / 1.1 - 1.0, 6)


def test_no_candle_before_t0_is_no_entry():
    closes = closes_from_candles(_candles(T0 + HOUR, [1.0, 1.1, 1.2]))
    label = forward_label(7, closes, T0, timedelta(hours=1))
    assert label.status == STATUS_NO_ENTRY
    assert label.forward_return is None


def test_stale_exit_is_no_exit_not_a_stale_move():
    closes = closes_from_candles(_candles(T0 - HOUR, [1.0, 1.1]))
    label = forward_label(7, closes, T0, timedelta(hours=24))
    assert label.status == STATUS_NO_EXIT
    assert label.forward_return is None


def test_exit_must_come_after_entry():
    closes = closes_from_candles(_candles(T0, [1.0]))
    label = forward_label(7, closes, T0, timedelta(hours=0))
    assert label.status != STATUS_OK or label.exit_close == label.entry_close


def test_non_positive_and_malformed_candles_are_dropped():
    rows = [
        {"timestamp": T0.isoformat(), "close": 0},
        {"timestamp": T0.isoformat(), "close": "bad"},
        {"close": 2.0},
        {"timestamp": (T0 + HOUR).isoformat(), "close": 3.0},
    ]
    assert closes_from_candles(rows) == [(T0 + HOUR, 3.0)]


def test_universe_labels_covers_every_requested_netuid_including_spot_only_keys():
    cache = {
        "1": {"candles": _candles(T0 - HOUR, [1.0, 2.0, 3.0])},
        "2.alpha": 0.5,
    }
    labels = universe_labels(cache, [1, 2, 3], T0, timedelta(hours=1))
    assert [label.netuid for label in labels] == [1, 2, 3]
    assert [label.status for label in labels] == [STATUS_OK, STATUS_NO_ENTRY, STATUS_NO_ENTRY]
    assert labels[0].forward_return == 0.5
