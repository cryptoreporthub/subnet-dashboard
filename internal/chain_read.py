from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


_BLOCK_HASH = re.compile(r"0x[0-9a-f]{64}")
# The universe layer may carry a read whose block is not a full 64-hex pin (a stubbed or probe-derived
# read). Such a read can say what is registered, but only a pinned read can be admitted: every admission
# check (receipt provenance, is_complete_snapshot, persisted reload) parses strictly.
_LOOSE_BLOCK_HASH = re.compile(r"0x[0-9a-f]+")
# Block placeholder for a read derived from a probe verdict, which has no block of its own.
UNPINNED_BLOCK_HASH = "0x0"
_MAX_NETUID = 65535
# A provider label, never a URL: a URL can carry an API key.
_RPC_LABEL = re.compile(r"[a-z][a-z0-9_-]{0,31}")


@dataclass(frozen=True)
class ChainRead:
    block_hash: str
    netuids: Tuple[int, ...]
    rpc: Optional[str] = None

    @property
    def is_pinned(self) -> bool:
        """True only for a full 64-hex block hash: the sole kind of read admission accepts."""
        return bool(_BLOCK_HASH.fullmatch(self.block_hash))

    @classmethod
    def parse(cls, raw: Any, *, pinned: bool = True) -> Optional["ChainRead"]:
        """Validate a chain read. `pinned=False` accepts any 0x-hex block hash (universe layer only);
        the default demands a full pin, and every admission path uses the default."""
        if not isinstance(raw, dict):
            return None
        block_hash = raw.get("block_hash")
        netuids = raw.get("netuids")
        pattern = _BLOCK_HASH if pinned else _LOOSE_BLOCK_HASH
        if not isinstance(block_hash, str) or not pattern.fullmatch(block_hash):
            return None
        if not isinstance(netuids, (list, tuple)) or not netuids:
            return None
        if any(type(n) is not int or not 0 < n <= _MAX_NETUID for n in netuids):
            return None
        if any(a >= b for a, b in zip(netuids, netuids[1:])):
            return None
        rpc = raw.get("rpc")
        if not isinstance(rpc, str) or not _RPC_LABEL.fullmatch(rpc):
            rpc = None
        return cls(block_hash, tuple(netuids), rpc)

    def to_dict(self) -> Dict[str, Any]:
        return {"block_hash": self.block_hash, "netuids": list(self.netuids), "rpc": self.rpc}
