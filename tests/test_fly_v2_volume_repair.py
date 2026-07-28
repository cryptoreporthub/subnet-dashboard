"""Volume placement detection for fly_v2_volume_repair.sh (logic mirror)."""

from __future__ import annotations


def volume_on_web(vol_id: str, attached: str, web_id: str, worker_id: str) -> bool:
    return bool(vol_id and attached and web_id and worker_id and attached == web_id)


def test_volume_on_web_detects_misplacement():
    assert volume_on_web("vol1", "webmachine", "webmachine", "workermachine")


def test_volume_on_worker_ok():
    assert not volume_on_web("vol1", "workermachine", "webmachine", "workermachine")


def test_volume_unattached():
    assert not volume_on_web("vol1", "", "webmachine", "workermachine")
