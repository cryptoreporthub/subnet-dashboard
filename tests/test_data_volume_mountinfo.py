"""Mountinfo parsing helpers (strict volume proof)."""

from __future__ import annotations

import os
from unittest import mock

import internal.data_volume as dv


def test_decode_mountinfo_path_octal_escapes():
    assert dv.decode_mountinfo_path("/app/data") == "/app/data"
    assert dv.decode_mountinfo_path("/app/my\\040dir") == "/app/my dir"
    assert dv.decode_mountinfo_path("a\\011b") == "a\tb"
    assert dv.decode_mountinfo_path("a\\012b") == "a\nb"
    assert dv.decode_mountinfo_path("a\\134b") == "a\\b"


def test_strict_mount_proof_matches_escaped_mount_point(tmp_path):
    root = os.path.realpath(str(tmp_path / "data"))
    os.makedirs(root)
    escaped = root.replace(" ", "\\040")
    line = f"999 998 0:42 / {escaped} rw,relatime - ext4 /dev/vdc rw"
    with mock.patch.object(dv, "_read_mountinfo", return_value=[line]):
        ok, why, facts = dv.strict_mount_proof(root)
    assert ok is True
    assert why == ""
    assert facts["mount_point"] == escaped
