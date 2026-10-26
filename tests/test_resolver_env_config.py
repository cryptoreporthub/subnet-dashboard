"""Malformed resolver env settings must not break the import of internal.council.resolver (#1506).

server.py swallows an import failure of the learning routes, so a typo in these
variables used to switch the learning loop off without a visible error.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

PROBE = (
    "import json, internal.council.resolver as r;"
    "print(json.dumps([r._PRICE_RETRY_CAP, r._EXPIRY_GRACE_MULTIPLE]))"
)


def _import_resolver(**env: str) -> list:
    child_env = {k: v for k, v in os.environ.items() if not k.startswith("RESOLVER_")}
    child_env.update(env)
    done = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr[-800:]
    return json.loads(done.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("raw", ["not-a-number", "", "2.5"])
def test_malformed_retry_cap_falls_back_to_default(raw):
    cap, _ = _import_resolver(RESOLVER_PRICE_RETRY_CAP=raw)

    assert cap == 3


@pytest.mark.parametrize("raw", ["0", "-4"])
def test_non_positive_retry_cap_falls_back_to_default(raw):
    cap, _ = _import_resolver(RESOLVER_PRICE_RETRY_CAP=raw)

    assert cap == 3


@pytest.mark.parametrize("raw", ["not-a-number", "nan", "inf", "-inf", "0", "-2"])
def test_bad_grace_multiple_falls_back_to_default(raw):
    _, grace = _import_resolver(RESOLVER_EXPIRY_GRACE_MULTIPLE=raw)

    assert grace == 4.0


def test_valid_settings_are_used():
    cap, grace = _import_resolver(RESOLVER_PRICE_RETRY_CAP="5", RESOLVER_EXPIRY_GRACE_MULTIPLE="2.5")

    assert (cap, grace) == (5, 2.5)
