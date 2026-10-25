"""Authoritative registry + price_cache rows for image seed builds (#1484 P1)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from internal.council.scorer_identity import repo_root

REGISTRY_REL = Path("config") / "registry.json"
PRICE_CACHE_REL = Path("data") / "price_cache.json"
UNIVERSE_REL = Path("data") / "subnet_universe.json"
COMMITTED_ROWS_REL = Path("data_seeds") / "authoritative_universe_rows.json"
IMAGE_SEED_NETUIDS = tuple(range(1, 129))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _registry_records(path: Path) -> Dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    return raw


def registry_name_for_netuid(registry: Dict[str, Any], netuid: int) -> Optional[str]:
    rec = registry.get(str(netuid)) or registry.get(netuid)
    if not isinstance(rec, dict):
        return None
    name = rec.get("name")
    return str(name).strip() if isinstance(name, str) and name.strip() else None


def latest_close_from_price_cache(block: Any) -> Optional[float]:
    if not isinstance(block, dict):
        return None
    candles = block.get("candles")
    if not isinstance(candles, list) or not candles:
        return None
    last = candles[-1]
    if not isinstance(last, dict):
        return None
    try:
        return float(last.get("close"))
    except (TypeError, ValueError):
        return None


def _universe_rows_by_netuid(path: Path) -> Dict[int, Dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("rows") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        raise ValueError("subnet_universe.json missing rows")
    out: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        netuid = row.get("netuid") if isinstance(row.get("netuid"), int) else row.get("id")
        if isinstance(netuid, str) and netuid.isdigit():
            netuid = int(netuid)
        if not isinstance(netuid, int):
            continue
        out[netuid] = row
    return out


def _rows_from_live_universe(
    netuids: Tuple[int, ...],
    *,
    universe_path: Path,
    registry_path: Path,
    cache_path: Path,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    universe = _universe_rows_by_netuid(universe_path)
    registry = _registry_records(registry_path) if registry_path.is_file() else {}
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    if not isinstance(cache, dict):
        raise ValueError("price_cache is not an object")

    rows: List[Dict[str, Any]] = []
    missing: List[int] = []
    for netuid in netuids:
        urow = universe.get(netuid)
        if not urow:
            missing.append(netuid)
            continue
        name = urow.get("name")
        if not isinstance(name, str) or not name.strip():
            name = registry_name_for_netuid(registry, netuid)
        if not name:
            missing.append(netuid)
            continue
        price = urow.get("price")
        try:
            price_f = float(price)
        except (TypeError, ValueError):
            block = cache.get(str(netuid)) or cache.get(netuid)
            close = latest_close_from_price_cache(block)
            if close is None:
                missing.append(netuid)
                continue
            price_f = close
        try:
            volume_f = float(urow.get("volume") or 0)
        except (TypeError, ValueError):
            volume_f = 0.0
        source = urow.get("source") or "taomarketcap"
        rows.append(
            {
                "netuid": netuid,
                "name": str(name).strip(),
                "price": price_f,
                "volume": volume_f,
                "source": str(source),
            }
        )
    if missing:
        raise ValueError(f"authoritative inputs missing netuids: {missing[:8]}…")

    market_provenance = {
        "universe_path": str(UNIVERSE_REL).replace("\\", "/"),
        "price_cache_path": str(PRICE_CACHE_REL).replace("\\", "/"),
        "universe_sha256": _sha256_file(universe_path),
        "price_cache_sha256": _sha256_file(cache_path),
        "netuid_count": len(netuids),
        "hydrate_row_count": len(rows),
    }
    return rows, market_provenance


def refresh_committed_authoritative_rows(
    netuids: Tuple[int, ...] = IMAGE_SEED_NETUIDS,
) -> Path:
    """Regenerate data_seeds/authoritative_universe_rows.json from live universe files."""
    root = repo_root()
    rows, prov = _rows_from_live_universe(
        netuids,
        universe_path=root / UNIVERSE_REL,
        registry_path=root / REGISTRY_REL,
        cache_path=root / PRICE_CACHE_REL,
    )
    out = root / COMMITTED_ROWS_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"rows": rows, "market_inputs": prov}, indent=2), encoding="utf-8")
    return out


def build_authoritative_hydrate_rows(
    netuids: Tuple[int, ...] = IMAGE_SEED_NETUIDS,
    *,
    universe_path: Optional[Path] = None,
    registry_path: Optional[Path] = None,
    price_cache_path: Optional[Path] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Hydrate rows from committed seed market file (prod image), or live universe when refreshing."""
    root = repo_root()
    committed = root / COMMITTED_ROWS_REL
    if universe_path is None and registry_path is None and price_cache_path is None and committed.is_file():
        payload = json.loads(committed.read_text(encoding="utf-8"))
        rows = payload.get("rows")
        prov = payload.get("market_inputs")
        if isinstance(rows, list) and isinstance(prov, dict) and len(rows) == len(netuids):
            return rows, prov

    uni_path = universe_path or (root / UNIVERSE_REL)
    reg_path = registry_path or (root / REGISTRY_REL)
    cache_path = price_cache_path or (root / PRICE_CACHE_REL)
    if not uni_path.is_file():
        raise FileNotFoundError(f"subnet_universe missing: {uni_path}")
    if not cache_path.is_file():
        raise FileNotFoundError(f"price_cache missing: {cache_path}")
    return _rows_from_live_universe(
        netuids,
        universe_path=uni_path,
        registry_path=reg_path,
        cache_path=cache_path,
    )
