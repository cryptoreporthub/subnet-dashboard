"""
Test weight propagation from Soul-Map through MindmapBridge to Selector.

Verifies that the Learner-updated expert weights in data/soul_map.json
are correctly read by the Selector via MindmapBridge.get_expert_weights().
"""

import json
import os
import tempfile

import pytest

from internal.council.mindmap_bridge import MindmapBridge
from internal.council.selector import Selector, DEFAULT_WEIGHTS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_soul_map(path, **overrides):
    """Write a minimal soul_map.json, merging any overrides."""
    base = {
        "soul_map_state": {"last_selector_output": {}, "updated_at": "2026-06-24T00:00:00Z"},
        "feedback_logs": [],
    }
    base.update(overrides)
    with open(path, "w") as f:
        json.dump(base, f, indent=2)


# ---------------------------------------------------------------------------
# MindmapBridge.get_expert_weights()
# ---------------------------------------------------------------------------


class TestGetExpertWeights:
    def test_from_adversarial_state(self):
        """Priority 1: adversarial_state.council_weights."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "soul_map.json")
            _write_soul_map(
                path,
                adversarial_state={
                    "council_weights": {
                        "quant": 0.4,
                        "hype": 0.3,
                        "contrarian": 0.15,
                        "technical": 0.15,
                    },
                },
            )
            bridge = MindmapBridge(persistence_path=path)
            assert bridge.get_expert_weights() == {
                "quant": 0.4, "hype": 0.3, "contrarian": 0.15, "technical": 0.15,
            }

    def test_from_soul_map_state_legacy(self):
        """Priority 2: soul_map_state.expert_weights."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "soul_map.json")
            _write_soul_map(
                path,
                soul_map_state={
                    "expert_weights": {
                        "quant": 0.35,
                        "hype": 0.35,
                        "contrarian": 0.15,
                        "technical": 0.15,
                    },
                    "last_selector_output": {},
                    "updated_at": "2026-06-24T00:00:00Z",
                },
            )
            bridge = MindmapBridge(persistence_path=path)
            assert bridge.get_expert_weights() == {
                "quant": 0.35, "hype": 0.35, "contrarian": 0.15, "technical": 0.15,
            }

    def test_from_top_level_expert_weights(self):
        """Priority 3: top-level expert_weights."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "soul_map.json")
            _write_soul_map(
                path,
                expert_weights={
                    "quant": 0.25,
                    "hype": 0.35,
                    "contrarian": 0.2,
                    "technical": 0.2,
                },
            )
            bridge = MindmapBridge(persistence_path=path)
            assert bridge.get_expert_weights() == {
                "quant": 0.25, "hype": 0.35, "contrarian": 0.2, "technical": 0.2,
            }

    def test_prefers_adversarial_over_top_level(self):
        """When both exist, adversarial_state.council_weights wins."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "soul_map.json")
            _write_soul_map(
                path,
                adversarial_state={
                    "council_weights": {
                        "quant": 0.5,
                        "hype": 0.2,
                        "contrarian": 0.2,
                        "technical": 0.1,
                    },
                },
                expert_weights={
                    "quant": 0.25,
                    "hype": 0.25,
                    "contrarian": 0.25,
                    "technical": 0.25,
                },
            )
            bridge = MindmapBridge(persistence_path=path)
            assert bridge.get_expert_weights() == {
                "quant": 0.5, "hype": 0.2, "contrarian": 0.2, "technical": 0.1,
            }

    def test_returns_empty_when_missing(self):
        """No weights stored anywhere → empty dict."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "soul_map.json")
            _write_soul_map(path)
            bridge = MindmapBridge(persistence_path=path)
            assert bridge.get_expert_weights() == {}

    def test_returns_empty_when_file_missing(self):
        """File does not exist → empty dict."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nonexistent.json")
            bridge = MindmapBridge(persistence_path=path)
            assert bridge.get_expert_weights() == {}


# ---------------------------------------------------------------------------
# Selector weight loading
# ---------------------------------------------------------------------------


class TestSelectorWeightPropagation:
    def test_loads_weights_from_soul_map(self):
        """Selector picks up top-level expert_weights via get_expert_weights()."""
        with tempfile.TemporaryDirectory() as tmp:
            sm_path = os.path.join(tmp, "soul_map.json")
            _write_soul_map(
                sm_path,
                expert_weights={
                    "quant": 0.1,
                    "hype": 0.4,
                    "contrarian": 0.4,
                    "technical": 0.1,
                },
            )
            bridge = MindmapBridge(persistence_path=sm_path)
            sel = Selector(mindmap_bridge=bridge, weights=None)
            assert sel.weights == {
                "quant": 0.1, "hype": 0.4, "contrarian": 0.4, "technical": 0.1,
            }

    def test_falls_back_to_defaults(self):
        """When no weights stored, Selector uses DEFAULT_WEIGHTS."""
        with tempfile.TemporaryDirectory() as tmp:
            sm_path = os.path.join(tmp, "soul_map.json")
            _write_soul_map(sm_path)
            bridge = MindmapBridge(persistence_path=sm_path)
            sel = Selector(mindmap_bridge=bridge, weights=None)
            assert sel.weights == DEFAULT_WEIGHTS

    def test_explicit_weights_override_soul_map(self):
        """Explicitly passed weights are used verbatim."""
        with tempfile.TemporaryDirectory() as tmp:
            sm_path = os.path.join(tmp, "soul_map.json")
            _write_soul_map(
                sm_path,
                expert_weights={
                    "quant": 0.1,
                    "hype": 0.2,
                    "contrarian": 0.3,
                    "technical": 0.4,
                },
            )
            bridge = MindmapBridge(persistence_path=sm_path)
            explicit = {"quant": 0.5, "hype": 0.2, "contrarian": 0.2, "technical": 0.1}
            sel = Selector(mindmap_bridge=bridge, weights=explicit)
            assert sel.weights == explicit
