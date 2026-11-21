"""Behavior of scripts/check_invariants.py: flags, passes, and the ratchet."""

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_invariants", REPO / "scripts" / "check_invariants.py"
)
ci = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ci)


def _scan_source(tmp_path, source):
    (tmp_path / "internal").mkdir()
    (tmp_path / "internal" / "mod.py").write_text(source, encoding="utf-8")
    return ci.scan(tmp_path)


def _rules(hits):
    return sorted((h["rule"], h["function"]) for h in hits)


def test_corrupt_store_read_as_empty_is_flagged(tmp_path):
    hits = _scan_source(
        tmp_path,
        (
            "import json\n"
            "def load(path):\n"
            "    try:\n"
            "        with open(path) as f:\n"
            "            return json.load(f)\n"
            "    except (json.JSONDecodeError, OSError):\n"
            "        return {}\n"
        ),
    )
    assert _rules(hits) == [("read-as-empty", "load")]


def test_missing_file_only_is_not_flagged(tmp_path):
    hits = _scan_source(
        tmp_path,
        (
            "import json\n"
            "def load(path):\n"
            "    try:\n"
            "        with open(path) as f:\n"
            "            return json.load(f)\n"
            "    except FileNotFoundError:\n"
            "        return {}\n"
        ),
    )
    assert hits == []


def test_swallowed_read_then_write_is_flagged(tmp_path):
    hits = _scan_source(
        tmp_path,
        (
            "def retry(path, save):\n"
            "    try:\n"
            "        existing = {1, 2}\n"
            "    except Exception:\n"
            "        existing = set()\n"
            "    save(existing)\n"
        ),
    )
    assert _rules(hits) == [("swallow-to-empty", "retry")]


def test_swallowed_default_in_read_only_builder_is_not_flagged(tmp_path):
    hits = _scan_source(
        tmp_path,
        (
            "def build(x):\n"
            "    try:\n"
            "        rows = compute(x)\n"
            "    except Exception:\n"
            "        rows = []\n"
            "    return rows\n"
        ),
    )
    assert hits == []


def test_nested_try_is_attributed_once_to_its_own_function(tmp_path):
    hits = _scan_source(
        tmp_path,
        (
            "import json\n"
            "def outer(path):\n"
            "    def inner():\n"
            "        try:\n"
            "            return json.load(open(path))\n"
            "        except (json.JSONDecodeError, OSError):\n"
            "            return {}\n"
            "    return inner()\n"
        ),
    )
    assert _rules(hits) == [("read-as-empty", "inner")]


def test_repo_has_no_hits_beyond_the_reviewed_baseline():
    assert ci.main(["--check", "--root", str(REPO)]) == 0


def test_repo_baseline_is_not_stale(tmp_path):
    """Every accepted key must still exist, so the baseline shrinks as debt is paid."""
    import json

    accepted = {
        e["key"]
        for e in json.loads((REPO / "scripts" / "invariants_baseline.json").read_text())
    }
    current = {h["key"] for h in ci.scan(REPO)}
    assert accepted <= current, f"stale baseline entries: {sorted(accepted - current)}"
