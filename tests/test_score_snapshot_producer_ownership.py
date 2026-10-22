"""PR-A / MC #1479 D1 — ownership predicate + fly truth table."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from internal.run_mode import score_snapshot_producer_enabled

REPO = Path(__file__).resolve().parents[1]

# MC #1479 part 1 — env slices only (not deploy wiring).
TRUTH_TABLE_ENV = [
    (
        "fly.toml v1 web",
        {
            "RUN_MODE": "web",
            "BACKGROUND_ON_WEB": "off",
            "INLINE_WORKER": "1",
            "ENABLE_INLINE_WORKER": "1",
            "WORKER_SPLIT_V2": "off",
            "WORKER_HEAVY": "essential",
        },
        False,
    ),
    (
        "fly.toml v1 inline worker",
        {"RUN_MODE": "worker", "WORKER_HEAVY": "essential"},
        True,
    ),
    (
        "v1 web BACKGROUND_ON_WEB=on (sibling worker)",
        {
            "RUN_MODE": "web",
            "BACKGROUND_ON_WEB": "on",
            "INLINE_WORKER": "1",
            "WORKER_SPLIT_V2": "off",
            "WORKER_HEAVY": "essential",
        },
        False,
    ),
    (
        "fly.worker-v2.toml web",
        {
            "RUN_MODE": "web",
            "BACKGROUND_ON_WEB": "off",
            "INLINE_WORKER": "0",
            "WORKER_SPLIT_V2": "off",
            "WORKER_HEAVY": "essential",
        },
        False,
    ),
    (
        "v2 worker group",
        {"RUN_MODE": "worker", "WORKER_HEAVY": "essential", "WORKER_SPLIT_V2": "on"},
        True,
    ),
    (
        "hop worker",
        {"RUN_MODE": "worker", "STAGE2_HOP": "1", "WORKER_HEAVY": "off"},
        False,
    ),
    (
        "legacy combined (no worker)",
        {
            "RUN_MODE": "web",
            "BACKGROUND_ON_WEB": "on",
            "INLINE_WORKER": "0",
            "WORKER_SPLIT_V2": "off",
        },
        True,
    ),
]


def _apply_env(monkeypatch, env: dict[str, str]) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for key in (
        "RUN_MODE",
        "BACKGROUND_ON_WEB",
        "INLINE_WORKER",
        "ENABLE_INLINE_WORKER",
        "WORKER_SPLIT_V2",
        "WORKER_HEAVY",
        "STAGE2_HOP",
    ):
        if key not in env:
            monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize(
    "label,env,expected_owner",
    TRUTH_TABLE_ENV,
    ids=[row[0] for row in TRUTH_TABLE_ENV],
)
def test_score_snapshot_producer_truth_table_env(label, env, expected_owner, monkeypatch):
    _apply_env(monkeypatch, env)
    assert score_snapshot_producer_enabled() is expected_owner


def _parse_fly_env(rel_path: str) -> dict[str, str]:
    data = tomllib.loads((REPO / rel_path).read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in (data.get("env") or {}).items()}


def _role_envs(fly_path: str, worker_overlay: dict[str, str] | None) -> list[tuple[str, dict[str, str]]]:
    base = _parse_fly_env(fly_path)
    roles: list[tuple[str, dict[str, str]]] = [("web", dict(base))]
    if worker_overlay:
        merged = dict(base)
        merged.update(worker_overlay)
        roles.append(("worker", merged))
    return roles


@pytest.mark.parametrize(
    "fly_path,worker_overlay",
    [
        ("fly.toml", {"RUN_MODE": "worker", "WORKER_HEAVY": "essential"}),
        (
            "fly.worker-v2.toml",
            {"RUN_MODE": "worker", "WORKER_HEAVY": "essential", "WORKER_SPLIT_V2": "on"},
        ),
    ],
)
def test_fly_topology_truth_table_exactly_one_producer(
    fly_path, worker_overlay, monkeypatch
):
    """Prod fly declarations → one owning role per topology."""
    owners = 0
    for _role, env in _role_envs(fly_path, worker_overlay):
        _apply_env(monkeypatch, env)
        if score_snapshot_producer_enabled():
            owners += 1
    assert owners == 1, f"{fly_path}: expected one producer role, saw {owners}"


def test_fly_worker_v2_hop_topology_has_zero_producers(monkeypatch):
    env = _parse_fly_env("fly.worker-v2-hop.toml")
    _apply_env(monkeypatch, env)
    assert score_snapshot_producer_enabled() is False
