"""F04 same-process soul-map persistence semantics."""

from __future__ import annotations

import json
import threading

import pytest

from internal.council import weights


def _write_weights(path) -> None:
    path.write_text(
        json.dumps(
            {
                "sentinel": "keep",
                "adversarial_state": {
                    "council_weights": {
                        "quant": 1.0,
                        "hype": 1.0,
                        "dark_horse": 1.0,
                        "technical": 1.0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def _run_forced_order(monkeypatch, calls):
    """Run real persistence methods with bounded waits outside the ledger transaction."""
    import contextlib

    from internal.store import ledger_db

    labels = tuple(calls)
    entered = {label: threading.Event() for label in labels}
    first_done = threading.Event()
    current = threading.local()
    errors = []
    results = {}
    original = ledger_db.transaction

    @contextlib.contextmanager
    def synchronized(path=None):
        label = current.label
        entered[label].set()
        assert entered[labels[0]].wait(2)
        assert entered[labels[1]].wait(2)
        if label == labels[1]:
            assert first_done.wait(2)
        with original(path) as conn:
            yield conn
        if label == labels[0]:
            first_done.set()

    monkeypatch.setattr(ledger_db, "transaction", synchronized)

    def run(label, operation):
        try:
            current.label = label
            results[label] = operation()
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=run, args=(label, operation))
        for label, operation in calls.items()
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert errors == []
    return results


def test_save_raw_preserves_ordered_same_key_replacement(tmp_path):
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps({"state": {"value": 0}}), encoding="utf-8")

    weights._save_raw({"state": {"value": 1}}, str(soul))
    weights._save_raw({"state": {"value": 2}}, str(soul))

    assert json.loads(soul.read_text(encoding="utf-8")) == {"state": {"value": 2}}


@pytest.mark.parametrize("first_expert", ["quant", "hype"])
def test_concurrent_disjoint_council_nudges_use_latest_state(
    tmp_path, monkeypatch, first_expert
):
    soul = tmp_path / "soul_map.json"
    _write_weights(soul)
    second_expert = "hype" if first_expert == "quant" else "quant"
    results = _run_forced_order(
        monkeypatch,
        {
            first_expert: lambda: weights.nudge_expert(first_expert, True, str(soul)),
            second_expert: lambda: weights.nudge_expert(second_expert, True, str(soul)),
        },
    )
    assert sorted(results.values()) == [1.02, 1.02]
    final = weights.load_weights(str(soul))
    assert final["quant"] == 1.02
    assert final["hype"] == 1.02
    assert json.loads(soul.read_text(encoding="utf-8"))["sentinel"] == "keep"


def test_same_key_nudges_compose(tmp_path):
    soul = tmp_path / "soul_map.json"
    _write_weights(soul)
    before = soul.read_bytes()

    assert weights.nudge_expert("quant", True, str(soul)) == 1.02
    assert weights.nudge_expert("quant", True, str(soul)) == 1.04

    assert weights.load_weights(str(soul))["quant"] == 1.04
    assert soul.read_bytes() == before


def _legacy_contrarian_soul(tmp_path):
    soul = tmp_path / "soul_map.json"
    (tmp_path / "predictions.json").write_text(
        json.dumps({"predictions": [], "resolved": []}), encoding="utf-8"
    )
    soul.write_text(
        json.dumps(
            {
                "sentinel": "keep",
                "adversarial_state": {
                    "council_weights": {
                        "quant": 1.0,
                        "hype": 1.0,
                        "contrarian": 1.8,
                        "technical": 1.0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return soul


def test_nudge_after_legacy_contrarian_import_applies_to_the_repaired_map(tmp_path):
    soul = _legacy_contrarian_soul(tmp_path)
    assert weights.nudge_expert("quant", True, str(soul)) == 1.02
    loaded = weights.load_weights(str(soul))
    assert "contrarian" not in loaded
    assert loaded["dark_horse"] == 1.0
    assert loaded["quant"] == 1.02


def test_concurrent_first_loads_of_a_legacy_map_agree(tmp_path):
    soul = _legacy_contrarian_soul(tmp_path)
    errors = []
    results = []

    def run():
        try:
            results.append(weights.load_weights(str(soul)))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert errors == []
    assert len(results) == 2
    assert all(result["quant"] == 1.0 and result["dark_horse"] == 1.0 for result in results)


def test_save_weights_prefers_soul_map_state_expected_snapshot(tmp_path):
    soul = tmp_path / "soul_map.json"
    soul.write_text(
        json.dumps(
            {
                "sentinel": "keep",
                "soul_map_state": {
                    "expert_weights": {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}
                },
                "expert_weights": {"quant": 1.7, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0},
            }
        ),
        encoding="utf-8",
    )
    expected = {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}
    weights.save_weights(
        {"quant": 1.2, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0},
        str(soul),
        expected_weights=expected,
    )
    assert weights.load_weights(str(soul))["quant"] == 1.2


def test_concurrent_nudges_on_a_legacy_map_compose(tmp_path):
    soul = _legacy_contrarian_soul(tmp_path)
    errors = []
    results = {}

    def run(expert, correct):
        try:
            results[expert] = weights.nudge_expert(expert, correct, str(soul))
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=run, args=("quant", True)),
        threading.Thread(target=run, args=("hype", False)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert errors == []
    assert results == {"quant": 1.02, "hype": 0.97}
    final = weights.load_weights(str(soul))
    assert final["quant"] == 1.02 and final["hype"] == 0.97
    assert json.loads(soul.read_text(encoding="utf-8"))["sentinel"] == "keep"


def test_stale_full_replacement_is_rejected_without_overwrite(tmp_path):
    soul = tmp_path / "soul_map.json"
    _write_weights(soul)
    expected = weights.load_weights(str(soul))
    assert weights.nudge_expert("quant", True, str(soul)) == 1.02

    with pytest.raises(weights.ConcurrentWeightUpdate):
        weights.save_weights(
            {"quant": 1.2, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0},
            str(soul),
            expected_weights=expected,
        )

    assert weights.load_weights(str(soul))["quant"] == 1.02


def test_concurrent_same_key_nudges_compose(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    _write_weights(soul)

    results = _run_forced_order(
        monkeypatch,
        {
            "first": lambda: weights.nudge_expert("quant", True, str(soul)),
            "second": lambda: weights.nudge_expert("quant", True, str(soul)),
        },
    )

    assert results == {"first": 1.02, "second": 1.04}
    assert weights.load_weights(str(soul))["quant"] == 1.04


@pytest.mark.parametrize("first_label", ["first", "second"])
def test_concurrent_save_weights_is_last_writer_wins(
    tmp_path, monkeypatch, first_label
):
    soul = tmp_path / "soul_map.json"
    _write_weights(soul)
    second_label = "second" if first_label == "first" else "first"
    maps = {
        "first": {"quant": 1.11, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0},
        "second": {"quant": 1.22, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0},
    }

    _run_forced_order(
        monkeypatch,
        {
            first_label: lambda: weights.save_weights(maps[first_label], str(soul)),
            second_label: lambda: weights.save_weights(maps[second_label], str(soul)),
        },
    )

    assert weights.load_weights(str(soul))["quant"] == maps[second_label]["quant"]


@pytest.mark.parametrize("first_label", ["first", "second"])
def test_concurrent_save_signal_weights_is_last_writer_wins(
    tmp_path, monkeypatch, first_label
):
    soul = tmp_path / "soul_map.json"
    _write_weights(soul)
    maps = {
        "first": {"hour": {"rsi_crossover": 1.11}, "day": {"macd_cross": 1.12}},
        "second": {"hour": {"rsi_crossover": 1.22}, "day": {"macd_cross": 1.23}},
    }
    second_label = "second" if first_label == "first" else "first"

    _run_forced_order(
        monkeypatch,
        {
            first_label: lambda: weights.save_signal_weights(maps[first_label], str(soul)),
            second_label: lambda: weights.save_signal_weights(maps[second_label], str(soul)),
        },
    )

    loaded = weights.load_signal_weights(str(soul))
    assert loaded["hour"]["rsi_crossover"] == maps[second_label]["hour"]["rsi_crossover"]
    assert loaded["day"]["macd_cross"] == maps[second_label]["day"]["macd_cross"]


@pytest.mark.parametrize("first_writer", ["council", "signal"])
def test_concurrent_disjoint_setters_preserve_both_sections(
    tmp_path, monkeypatch, first_writer
):
    soul = tmp_path / "soul_map.json"
    _write_weights(soul)
    second_writer = "signal" if first_writer == "council" else "council"
    council_map = {"quant": 1.31, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}
    signal_map = {"hour": {"rsi_crossover": 1.41}, "day": {"macd_cross": 1.42}}
    operations = {
        "council": lambda: weights.save_weights(council_map, str(soul)),
        "signal": lambda: weights.save_signal_weights(signal_map, str(soul)),
    }

    _run_forced_order(
        monkeypatch,
        {first_writer: operations[first_writer], second_writer: operations[second_writer]},
    )

    assert weights.load_weights(str(soul))["quant"] == 1.31
    loaded = weights.load_signal_weights(str(soul))
    assert loaded["hour"]["rsi_crossover"] == 1.41
    assert loaded["day"]["macd_cross"] == 1.42


def test_save_worker_exception_propagates(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    _write_weights(soul)
    from internal.store import ledger_db

    def boom(*_args, **_kwargs):
        raise RuntimeError("worker persistence failure")

    monkeypatch.setattr(ledger_db, "transaction", boom)
    with pytest.raises(RuntimeError, match="worker persistence failure"):
        weights.save_weights(
            {"quant": 1.1, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0},
            str(soul),
        )
    with pytest.raises(RuntimeError, match="worker persistence failure"):
        weights.save_signal_weights({"hour": {"rsi_crossover": 1.1}}, str(soul))


def test_signal_and_impact_nudges_tolerate_unrelated_malformed_signal(tmp_path):
    soul = tmp_path / "soul_map.json"
    soul.write_text(
        json.dumps(
            {
                "sentinel": "keep",
                "adversarial_state": {
                    "signal_weights": {
                        "hour": {"rsi_crossover": 1.0, "bad": {"not": "numeric"}}
                    },
                    "impact_strength": 1.0,
                },
            }
        ),
        encoding="utf-8",
    )

    assert weights.nudge_signal_weight("hour", "rsi_crossover", True, str(soul)) == 1.02
    assert weights.nudge_impact_strength(True, tier="small", path=str(soul)) == 1.02
    assert weights.load_signal_weights(str(soul))["hour"]["rsi_crossover"] == 1.02
    assert weights.load_impact_strength(str(soul)) == 1.02
    assert json.loads(soul.read_text(encoding="utf-8"))["sentinel"] == "keep"


def test_failed_weight_delivery_retries_without_double_application(
    tmp_path, monkeypatch
):
    import sqlite3

    from internal.store import ledger_db

    soul = tmp_path / "soul_map.json"
    _write_weights(soul)
    weights.load_weights(str(soul))
    original = ledger_db.apply_changes
    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise sqlite3.OperationalError("simulated write failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(ledger_db, "apply_changes", fail_once)

    assert weights.nudge_expert("quant", True, str(soul)) is None
    assert weights.load_weights(str(soul))["quant"] == 1.0
    assert weights.nudge_expert("quant", True, str(soul)) == 1.02
    assert weights.load_weights(str(soul))["quant"] == 1.02
