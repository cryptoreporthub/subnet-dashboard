from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


_BLOCK_HASH = re.compile(r"0x[0-9a-f]{64}")
_MAX_NETUID = 65535


@dataclass(frozen=True)
class ChainRead:
    block_hash: str
    netuids: Tuple[int, ...]

    @classmethod
    def parse(cls, raw: Any) -> Optional["ChainRead"]:
        if not isinstance(raw, dict):
            return None
        block_hash = raw.get("block_hash")
        netuids = raw.get("netuids")
        if not isinstance(block_hash, str) or not _BLOCK_HASH.fullmatch(block_hash):
            return None
        if not isinstance(netuids, (list, tuple)) or not netuids:
            return None
        if any(type(n) is not int or not 0 < n <= _MAX_NETUID for n in netuids):
            return None
        if any(a >= b for a, b in zip(netuids, netuids[1:])):
            return None
        return cls(block_hash, tuple(netuids))

    def to_dict(self) -> Dict[str, Any]:
        return {"block_hash": self.block_hash, "netuids": list(self.netuids)}
