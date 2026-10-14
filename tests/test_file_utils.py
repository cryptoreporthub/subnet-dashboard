"""Atomic JSON write helpers."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from internal.file_utils import safe_write_json


def test_safe_write_json_concurrent_writers_do_not_share_temp(tmp_path):
    target = tmp_path / "whale_intelligence.json"
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def writer(key: str, letter: str) -> None:
        try:
            barrier.wait()
            safe_write_json(str(target), {key: letter * 64})
        except BaseException as exc:
            errors.append(exc)

    t_a = threading.Thread(target=writer, args=("a", "A"))
    t_b = threading.Thread(target=writer, args=("b", "B"))
    t_a.start()
    t_b.start()
    t_a.join()
    t_b.join()

    assert not errors
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert set(payload.keys()) == {"a"} or set(payload.keys()) == {"b"}
    assert payload[list(payload.keys())[0]] in ("A" * 64, "B" * 64)
    assert not list(tmp_path.glob("tmp*.json"))
    assert list(tmp_path.glob("whale_intelligence.json.*.tmp")) == []
