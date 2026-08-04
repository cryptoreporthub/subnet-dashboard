"""Phase 2 SA6 — regression gate (bundle + counts)."""

import subprocess
import sys


def test_phase2_module_bundle_passes():
    """All Phase 2 slice tests + contract guard."""
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_phase2_telegram_desk.py",
            "tests/test_phase2_picks_radar.py",
            "tests/test_phase2_pulse_predictions.py",
            "tests/test_phase2_social_health.py",
            "tests/test_tribunal_hero_live.py",
            "tests/test_ba_tranche1_empty_states.py",
            "tests/test_endpoint_contract.py",
            "-q",
            "--tb=no",
        ],
        capture_output=True,
        text=True,
        cwd=".",
        env={**__import__("os").environ, "PYTHONPATH": "."},
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_phase2_completion_doc_exists():
    body = open("cursor-agents-communication/phase-2-completion-status.md", encoding="utf-8").read()
    assert "#809" in body
    assert "1615 passed" in body or "regression" in body.lower()
