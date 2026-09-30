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
                }
            }
        ),
        encoding="utf-8",
    )


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
    entered = {expert: threading.Event() for expert in (first_expert, second_expert)}
    first_done = threading.Event()
    original_write = __import__("internal.store.soul_map_io", fromlist=["write_soul_map"]).write_soul_map
    current_expert = threading.local()
    errors = []

    def synchronized_write(mutator, path):
        expert = current_expert.name
        entered[expert].set()
        assert entered[first_expert].wait(2)
        assert entered[second_expert].wait(2)
        if expert == second_expert:
            assert first_done.wait(2)
        result = original_write(mutator, path)
        if expert == first_expert:
            first_done.set()
        return result

    monkeypatch.setattr("internal.store.soul_map_io.write_soul_map", synchronized_write)

    results = {}

    def run(expert):
        try:
            current_expert.name = expert
            results[expert] = weights.nudge_expert(expert, True, str(soul))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(expert,)) for expert in (first_expert, second_expert)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert errors == []
    assert sorted(results.values()) == [1.02, 1.02]
    final = weights.load_weights(str(soul))
    assert final["quant"] == 1.02
    assert final["hype"] == 1.02
    assert json.loads(soul.read_text(encoding="utf-8"))["sentinel"] == "keep"


def test_same_key_nudges_compose_and_mirror_quant(tmp_path):
    soul = tmp_path / "soul_map.json"
    _write_weights(soul)

    assert weights.nudge_expert("quant", True, str(soul)) == 1.02
    assert weights.nudge_expert("quant", True, str(soul)) == 1.04

    data = json.loads(soul.read_text(encoding="utf-8"))
    assert data["adversarial_state"]["council_weights"]["quant"] == 1.04
    assert data["expert_weights"]["quant"] == 1.04
    assert data["sentinel"] == "keep"


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
    data = json.loads(soul.read_text(encoding="utf-8"))
    assert data["sentinel"] == "keep"
    assert data["adversarial_state"]["signal_weights"]["hour"]["rsi_crossover"] == 1.02
    assert data["adversarial_state"]["impact_strength"] == 1.02


def test_failed_weight_delivery_retries_without_double_application(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    _write_weights(soul)

    import internal.store.soul_map_io as soul_map_io

    original_replace = soul_map_io.os.replace
    attempts = 0

    def fail_once(src, dst):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("simulated delivery failure")
        return original_replace(src, dst)

    monkeypatch.setattr(soul_map_io.os, "replace", fail_once)

    # This only covers a failure before os.replace; delivery/exactly-once after
    # replace is intentionally outside the guarantee.
    assert weights.nudge_expert("quant", True, str(soul)) is None
    assert weights.load_weights(str(soul))["quant"] == 1.0
    assert weights.nudge_expert("quant", True, str(soul)) == 1.02
    assert weights.load_weights(str(soul))["quant"] == 1.02
