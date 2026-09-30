"""F04 same-process soul-map persistence semantics."""

from __future__ import annotations

import concurrent.futures
import json

from internal.council import weights


def _write_weights(path) -> None:
    path.write_text(
        json.dumps(
            {
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


def test_concurrent_disjoint_council_nudges_use_latest_state(tmp_path):
    soul = tmp_path / "soul_map.json"
    _write_weights(soul)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda expert: weights.nudge_expert(expert, True, str(soul)),
                ("quant", "hype"),
            )
        )

    assert sorted(results) == [1.02, 1.02]
    final = weights.load_weights(str(soul))
    assert final["quant"] == 1.02
    assert final["hype"] == 1.02


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

    assert weights.nudge_expert("quant", True, str(soul)) is None
    assert weights.load_weights(str(soul))["quant"] == 1.0
    assert weights.nudge_expert("quant", True, str(soul)) == 1.02
    assert weights.load_weights(str(soul))["quant"] == 1.02
