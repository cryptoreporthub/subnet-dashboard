"""Read-only soul_map.json census for Fly ssh. No writes."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    candidates = [
        Path("data/soul_map.json"),
        Path("/data/soul_map.json"),
        Path("/app/data/soul_map.json"),
    ]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        print("SOUL_MAP_MISSING")
        return 2
    raw = path.read_bytes()
    total = len(raw)
    print(f"path={path}")
    print(f"total_bytes={total}")
    print(f"mtime_ns={path.stat().st_mtime_ns}")
    d = json.loads(raw)

    rows = []
    for k, v in d.items():
        b = len(json.dumps(v, separators=(",", ":")).encode())
        n = len(v) if isinstance(v, (list, dict)) else None
        rows.append((b, k, type(v).__name__, n))
    rows.sort(reverse=True)
    print("=== top_level_key_byte_share ===")
    for b, k, ty, n in rows:
        pct = (100.0 * b / total) if total else 0.0
        extra = f" len={n}" if n is not None else ""
        print(f"{k}\t{b}\t{pct:.2f}%\t{ty}{extra}")

    arrays: list[tuple[int, str]] = []

    def walk(obj, prefix: str = "") -> None:
        if isinstance(obj, list):
            arrays.append((len(obj), prefix or "(root_list)"))
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                p = f"{prefix}.{k}" if prefix else k
                if isinstance(v, list):
                    arrays.append((len(v), p))
                elif isinstance(v, dict):
                    for k2, v2 in v.items():
                        p2 = f"{p}.{k2}"
                        if isinstance(v2, list):
                            arrays.append((len(v2), p2))

    walk(d)
    arrays.sort(reverse=True)
    print("=== top5_arrays_by_length ===")
    for n, p in arrays[:5]:
        print(f"{p}\t{n}")

    print("=== required_array_lengths ===")
    sched = d.get("prediction_resolver_scheduler")
    if isinstance(sched, dict) and isinstance(sched.get("cycle_history"), list):
        print(f"cycle_history\t{len(sched['cycle_history'])}")
    else:
        print("cycle_history\tmissing_or_not_list")

    for name in ("dispositions", "traces", "subnets", "predictions"):
        v = d.get(name)
        if isinstance(v, list):
            print(f"{name}\t{len(v)}")
            continue
        found = next((n for n, p in arrays if p == name or p.endswith("." + name)), None)
        if found is not None:
            print(f"{name}\t{found}")
        elif name not in d:
            print(f"{name}\tmissing")
        else:
            print(f"{name}\t{type(v).__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
