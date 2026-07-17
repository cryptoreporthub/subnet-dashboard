"""§27-4 — nudge_expert single path."""
from internal.council.weights import load_weights, nudge_expert, save_weights


def test_nudge_expert_correct_increases_weight(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text('{"adversarial_state":{"council_weights":{"quant":1.0,"hype":1.0,"dark_horse":1.0,"technical":1.0}}}')
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))

    after = nudge_expert("quant", True, str(soul))
    assert after == 1.02
    assert load_weights(str(soul))["quant"] == 1.02


def test_nudge_expert_wrong_decreases_weight(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text('{"adversarial_state":{"council_weights":{"quant":1.0,"hype":1.0,"dark_horse":1.0,"technical":1.0}}}')
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))

    after = nudge_expert("hype", False, str(soul))
    assert after == 0.97
    assert load_weights(str(soul))["hype"] == 0.97


def test_nudge_expert_unknown_returns_none(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text('{"adversarial_state":{"council_weights":{"quant":1.0,"hype":1.0,"dark_horse":1.0,"technical":1.0}}}')
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))

    assert nudge_expert("unknown_expert", True, str(soul)) is None
