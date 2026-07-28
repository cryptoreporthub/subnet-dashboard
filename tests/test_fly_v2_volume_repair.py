"""Volume placement detection for fly_v2_volume_repair.sh (logic mirror)."""

from __future__ import annotations


def machine_process_group(machine: dict) -> str:
    meta = (machine.get("config") or {}).get("metadata") or {}
    return (
        meta.get("fly_process_group")
        or meta.get("process_group")
        or machine.get("process_group")
        or "web"
    ).lower()


def volume_on_web(vol_id: str, attached: str, web_id: str, worker_id: str) -> bool:
    return bool(vol_id and attached and web_id and worker_id and attached == web_id)


def test_machine_process_group_from_metadata():
    m = {"id": "w1", "config": {"metadata": {"fly_process_group": "worker"}}}
    assert machine_process_group(m) == "worker"


def test_machine_process_group_defaults_web():
    assert machine_process_group({"id": "w1"}) == "web"


def test_volume_on_web_detects_misplacement():
    assert volume_on_web("vol1", "webmachine", "webmachine", "workermachine")


def test_volume_on_worker_ok():
    assert not volume_on_web("vol1", "workermachine", "webmachine", "workermachine")


def test_volume_unattached():
    assert not volume_on_web("vol1", "", "webmachine", "workermachine")
