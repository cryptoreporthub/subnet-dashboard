"""Global search for command palette (§28-3)."""

from __future__ import annotations

import re
from typing import Any, Dict, List

_SS58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{40,}$")


def global_search(query: str, limit: int = 8) -> List[Dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []
    out: List[Dict[str, Any]] = []
    seen = set()

    def add(item: Dict[str, Any]) -> None:
        key = (item.get("type"), item.get("url"))
        if key in seen or len(out) >= limit:
            return
        seen.add(key)
        out.append(item)

    if q.isdigit():
        n = int(q)
        add({"type": "subnet", "label": f"Subnet SN{n}", "url": f"/subnet/{n}", "hint": "netuid"})

    if _SS58_RE.match(q):
        short = q[:10] + "…" + q[-4:] if len(q) > 16 else q
        add({"type": "wallet", "label": short, "url": f"/wallet/{q}", "hint": "coldkey"})

    ql = q.lower()
    try:
        from server import load_data

        registry = load_data("config/registry.json")
        if isinstance(registry, dict):
            for key, row in registry.items():
                if not isinstance(row, dict):
                    continue
                netuid = row.get("netuid", row.get("id", key))
                try:
                    netuid = int(netuid)
                except (TypeError, ValueError):
                    continue
                name = str(row.get("name") or "")
                if ql in name.lower() or ql == str(netuid):
                    add(
                        {
                            "type": "subnet",
                            "label": f"{name or 'SN' + str(netuid)} (SN{netuid})",
                            "url": f"/subnet/{netuid}",
                            "hint": "registry",
                        }
                    )
    except Exception:
        pass

    try:
        from internal.learning.predictions_store import load_predictions

        data = load_predictions()
        for bucket in ("resolved", "predictions"):
            for pred in data.get(bucket) or []:
                if not isinstance(pred, dict):
                    continue
                pid = str(pred.get("id") or "")
                if not pid:
                    continue
                if ql in pid.lower():
                    netuid = pred.get("netuid")
                    name = pred.get("name") or (f"SN{netuid}" if netuid is not None else "Graded call")
                    add(
                        {
                            "type": "pick",
                            "label": f"{name} · {pid[:12]}…",
                            "url": f"/share/call/{pid}",
                            "hint": "graded call",
                        }
                    )
    except Exception:
        pass

    return out[:limit]
