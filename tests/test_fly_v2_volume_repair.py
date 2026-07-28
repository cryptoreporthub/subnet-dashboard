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


def worker_vm_internal_url(machine_id: str, app: str) -> str:
    return f"http://{machine_id}.vm.{app}.internal:8080"


def worker_private_ip_url(private_ip: str) -> str:
    return f"http://[{private_ip}]:8080"


def pick_worker_internal_url(machines: list, app: str) -> str | None:
    workers = [m for m in machines if machine_process_group(m) == "worker"]
    if not workers:
        return None
    m = workers[0]
    ip = (m.get("private_ip") or "").strip()
    if ip:
        return worker_private_ip_url(ip)
    mid = m.get("id") or ""
    return worker_vm_internal_url(mid, app) if mid else None


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


def test_pick_worker_internal_url():
    machines = [
        {"id": "web1", "config": {"metadata": {"fly_process_group": "web"}}},
        {
            "id": "wrk1",
            "private_ip": "fdaa:0:3b99:a7b:8aeb:fea3:148b:2",
            "config": {"metadata": {"fly_process_group": "worker"}},
        },
    ]
    url = pick_worker_internal_url(machines, "subnet-dashboard")
    assert url == "http://[fdaa:0:3b99:a7b:8aeb:fea3:148b:2]:8080"
