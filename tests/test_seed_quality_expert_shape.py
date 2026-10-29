"""validate_shipped_seed: a row must carry the whole council, not one expert plus junk (#1484 round 3).

The producer's `_expert_contributions` returns all four council experts for every row, and the
committed seed has all four (plus extras such as signal_contributions) on all 128 rows. The old gate
accepted any dict with two keys of which one was a council name, e.g. {"quant": 1, "junk": "x"}.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from internal.council.seed_quality import validate_shipped_seed

REPO = Path(__file__).resolve().parents[1]
COUNCIL = ("quant", "hype", "dark_horse", "technical")


@pytest.fixture
def seed():
    return json.loads((REPO / "data_seeds" / "score_snapshots.json").read_text(encoding="utf-8"))


def _with_contributions(seed, contributions):
    out = copy.deepcopy(seed)
    out["day"][0]["expert_contributions"] = contributions
    return out


def test_the_committed_seed_is_still_accepted(seed):
    assert validate_shipped_seed(seed) == (True, "ok")


def test_a_full_council_with_extra_keys_is_accepted(seed):
    full = {**{name: 0.5 for name in COUNCIL}, "signal_contributions": {}, "active_signals": []}
    assert validate_shipped_seed(_with_contributions(seed, full)) == (True, "ok")


@pytest.mark.parametrize(
    "contributions",
    [
        {"quant": 0.5, "junk": "x"},
        {"quant": 0.5, "junk": 1.0},
        {"quant": 0.5, "hype": 0.5, "technical": 0.5},
        {"quant": 0.5, "hype": 0.5, "dark_horse": 0.5, "technical": "0.5"},
        {"quant": 0.5, "hype": 0.5, "dark_horse": 0.5, "technical": None},
        {"quant": 0.5, "hype": 0.5, "dark_horse": 0.5, "technical": True},
        {"quant": 0.5, "hype": 0.5, "dark_horse": 0.5, "technical": float("nan")},
        {"quant": 0.5, "hype": 0.5, "dark_horse": 0.5, "technical": float("inf")},
        {"alpha": 0.1, "beta": 0.2, "gamma": 0.3, "delta": 0.4},
    ],
    ids=["one_plus_junk_str", "one_plus_junk_num", "three_of_four", "str_value", "none_value", "bool_value", "nan", "inf", "four_unknown"],
)
def test_a_row_that_is_not_the_whole_council_is_rejected(seed, contributions):
    ok, reason = validate_shipped_seed(_with_contributions(seed, contributions))
    assert ok is False
    assert reason in ("expert_contributions_not_council_shaped", "missing_expert_contributions")


@pytest.mark.parametrize("contributions", [None, {}, [], "quant", {"quant": 0.5}])
def test_missing_or_tiny_contributions_keep_their_own_reason(seed, contributions):
    assert validate_shipped_seed(_with_contributions(seed, contributions)) == (False, "missing_expert_contributions")


def test_the_check_applies_to_every_row_not_just_the_first(seed):
    seed["day"][-1]["expert_contributions"] = {"quant": 0.5, "junk": "x"}
    assert validate_shipped_seed(seed)[0] is False


@pytest.mark.parametrize("huge", [10**400, -(10**400)], ids=["positive", "negative"])
def test_an_oversized_integer_score_is_rejected_without_raising(seed, huge):
    """``math.isfinite(10**400)`` raises OverflowError; the gate must answer with a reason (#1484 Ditto r5)."""
    out = copy.deepcopy(seed)
    out["day"][0]["expert_contributions"] = {**{name: 0.5 for name in COUNCIL}, "quant": huge}
    ok, reason = validate_shipped_seed(out)
    assert ok is False
    assert reason == "expert_contributions_not_council_shaped"


def test_a_large_but_representable_integer_expert_value_is_a_score(seed):
    out = copy.deepcopy(seed)
    out["day"][0]["expert_contributions"] = {**{name: 0.5 for name in COUNCIL}, "quant": 10**300}
    assert validate_shipped_seed(out) == (True, "ok")


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan"), "x"], ids=["inf", "-inf", "nan", "str"])
@pytest.mark.parametrize("key", ["day_succeeded_count", "day_expected_count"])
def test_a_non_finite_build_count_is_rejected_without_raising(seed, key, bad):
    """int(float("inf")) raises OverflowError, the same crash class as the oversized scores (#1484 Ditto r5)."""
    out = copy.deepcopy(seed)
    out["build_provenance"][key] = bad
    assert validate_shipped_seed(out) == (False, "bad_provenance_counts")


@pytest.mark.parametrize("bad", [128.9, 128.1, 128.0, True, False, None, "128"], ids=repr)
@pytest.mark.parametrize("key", ["day_succeeded_count", "day_expected_count"])
def test_a_non_integer_build_count_is_rejected(seed, key, bad):
    """int() would truncate 128.9 to 128 and read True as 1, letting a malformed record pass (#1484 Ditto r15)."""
    out = copy.deepcopy(seed)
    assert out["build_provenance"][key] == 128  # the committed seed's count is a real int
    out["build_provenance"][key] = bad
    assert validate_shipped_seed(out) == (False, "bad_provenance_counts")
