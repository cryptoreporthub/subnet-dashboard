#!/usr/bin/env python3
"""Gecko vs chain validation protocol (#1395 Fix 5).

Live mode: GeckoTerminal hourly OHLCV with ``currency=token`` (#1397) compared to
Blockmachine reserve ratio at ``resolve_block_at`` timestamps.

Fixture mode: ``--input`` JSON with per-subnet matched hour data (no network).

Usage:
  PYTHONPATH=. python scripts/gecko_step4_validation.py --input tests/fixtures/gecko_validation/synthetic_pass.json
  PYTHONPATH=. python scripts/gecko_step4_validation.py --subnet-limit 5 --output /tmp/gecko_report.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from internal.chain_price.block_resolve import resolve_block_at
from internal.chain_price.config import rpc_provider_clients
from internal.chain_price.gecko_validation import (
    MatchedHour,
    SubnetValidationInput,
    evaluate_gecko_validation,
    subnets_from_serializable,
)
from internal.chain_price.reader import ChainReader
from internal.chain_price.storage_keys import map_key_hex
from internal.chain_client import (
    _decode_scale_u64,
    _hex_to_bytes,
    _parse_retry_after_header,
    note_rate_limit,
)
from internal.indicators.price_fetcher import gecko_ohlcv_guarantees_alpha_in_tao

GECKO_API = "https://api.geckoterminal.com/api/v2"
PAIRS_PATH = _ROOT / "config" / "price_pairs.json"
DEFAULT_OUTPUT = Path("/tmp/gecko_step4_validation_report.json")
GECKO_MIN_INTERVAL_S = 60.0 / 28.0
GECKO_429_MAX_CONSECUTIVE = 3


def _git_sha() -> str:
    try:
        return (
            subprocess.check_output(["git", "-C", str(_ROOT), "rev-parse", "HEAD"], text=True)
            .strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _load_gecko_mapped_pairs(limit: int) -> List[Tuple[int, str, str, Dict[str, Any]]]:
    with PAIRS_PATH.open(encoding="utf-8") as f:
        pairs = json.load(f)
    mapped: List[Tuple[int, str, str, Dict[str, Any]]] = []
    for key, val in pairs.items():
        if not isinstance(val, dict):
            continue
        gt = val.get("geckoterminal")
        if not isinstance(gt, dict):
            continue
        if not gecko_ohlcv_guarantees_alpha_in_tao(gt):
            continue
        mapped.append((int(key), str(gt["network"]), str(gt["pool"]), gt))
    mapped.sort(key=lambda x: x[0])
    return mapped[:limit] if limit > 0 else mapped


def _gecko_params(gt: Dict[str, Any], limit_hours: int) -> Dict[str, Any]:
    params: Dict[str, Any] = {"limit": limit_hours, "currency": "token"}
    price_token = gt.get("price_token")
    if price_token in ("base", "quote"):
        params["token"] = str(price_token)
    elif gt.get("base_is_alpha") is False:
        params["token"] = "quote"
    else:
        params["token"] = "base"
    return params


def _fetch_gecko_ohlcv(network: str, pool: str, gt: Dict[str, Any], limit_hours: int) -> List[Any]:
    url = f"{GECKO_API}/networks/{network}/pools/{pool}/ohlcv/hour"
    consecutive_429 = 0
    while True:
        resp = requests.get(url, params=_gecko_params(gt, limit_hours), timeout=30)
        if resp.status_code == 429:
            consecutive_429 += 1
            if consecutive_429 >= GECKO_429_MAX_CONSECUTIVE:
                raise RuntimeError("gecko_http_429")
            wait_s = note_rate_limit(GECKO_API, _parse_retry_after_header(resp))
            time.sleep(max(wait_s, GECKO_MIN_INTERVAL_S))
            continue
        resp.raise_for_status()
        break
    body = resp.json()
    data = body.get("data") if isinstance(body, dict) else None
    attrs = data.get("attributes") if isinstance(data, dict) else None
    ohlcv = attrs.get("ohlcv_list") if isinstance(attrs, dict) else []
    if not isinstance(ohlcv, list):
        raise RuntimeError("unexpected_gecko_shape")
    return ohlcv


def _decode_u64_storage(raw: Any) -> Optional[int]:
    if raw is None or raw == "0x" or raw == "0x00":
        return None
    try:
        return _decode_scale_u64(_hex_to_bytes(raw))
    except (TypeError, ValueError):
        return None


def _reserve_price_tao(reader: ChainReader, netuid: int, block_hash: str) -> Optional[float]:
    keys = [map_key_hex(b"SubnetTAO", netuid), map_key_hex(b"SubnetAlphaIn", netuid)]
    batch, outcome = reader.call("state_queryStorageAt", [keys, block_hash])
    if outcome != "ok" or not batch:
        return None
    entry = batch[0] if isinstance(batch[0], dict) else {}
    changes = entry.get("changes")
    if not changes:
        return None
    by_key = {row[0]: row[1] for row in changes if row}
    tao_raw = _decode_u64_storage(by_key.get(keys[0]))
    alpha_raw = _decode_u64_storage(by_key.get(keys[1]))
    if not tao_raw or not alpha_raw:
        return None
    return tao_raw / alpha_raw


def _live_probe_subnets(
    mapped: List[Tuple[int, str, str, Dict[str, Any]]],
    *,
    window_hours: int,
    reader: ChainReader,
) -> List[SubnetValidationInput]:
    results: List[SubnetValidationInput] = []
    last_gecko = 0.0
    for netuid, network, pool, gt in mapped:
        sub = SubnetValidationInput(netuid=netuid, pool=pool)
        try:
            elapsed = time.monotonic() - last_gecko
            if elapsed < GECKO_MIN_INTERVAL_S:
                time.sleep(GECKO_MIN_INTERVAL_S - elapsed)
            ohlcv = _fetch_gecko_ohlcv(network, pool, gt, window_hours)
            last_gecko = time.monotonic()
        except Exception as exc:
            sub.error = str(exc)[:160]
            results.append(sub)
            continue

        now_ts = int(time.time())
        sorted_ohlcv = sorted(
            (row for row in ohlcv if isinstance(row, (list, tuple)) and len(row) >= 5),
            key=lambda row: int(row[0]),
        )
        completed = [
            row
            for row in sorted_ohlcv
            if int(row[0]) + 3600 <= now_ts
        ]
        matched: List[MatchedHour] = []
        for item in completed[-window_hours:]:
            ts, _o, _h, _l, close, *_rest = item
            target_ms = (int(ts) + 3600) * 1000
            block, block_hash, outcome = resolve_block_at(
                reader, target_ms, search="bracketed"
            )
            if outcome != "ok" or block is None or not block_hash:
                continue
            chain_px = _reserve_price_tao(reader, netuid, block_hash)
            if chain_px is None or float(close) <= 0:
                continue
            matched.append(
                MatchedHour(
                    gecko_close=float(close),
                    chain_price_tao=chain_px,
                    hour_unix=int(ts),
                )
            )
            time.sleep(0.05)
        sub.matched = matched
        results.append(sub)
        time.sleep(0.2)
    return results


def _report_from_subnets(
    subnets: List[SubnetValidationInput],
    *,
    window_hours: int,
    git_sha: str,
    mode: str,
) -> Dict[str, Any]:
    evaluation = evaluate_gecko_validation(subnets)
    return {
        "protocol": "gecko_step4_validation",
        "version": 1,
        "git_sha": git_sha,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "window_hours": window_hours,
        "currency": "token",
        **evaluation,
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gecko vs chain Step 4 validation protocol")
    parser.add_argument(
        "--input",
        type=Path,
        help="JSON file with {subnets: [...]} fixture rows (no live RPC)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Write report JSON here",
    )
    parser.add_argument("--subnet-limit", type=int, default=20, help="Max Gecko-mapped subnets (live)")
    parser.add_argument("--window-hours", type=int, default=48, help="OHLCV window (hours)")
    args = parser.parse_args(argv)

    git_sha = _git_sha()
    if args.input:
        with args.input.open(encoding="utf-8") as f:
            payload = json.load(f)
        rows = payload.get("subnets") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            parser.error("--input JSON must contain a subnets list")
        subnets = subnets_from_serializable(rows)
        mode = "fixture"
    else:
        clients = rpc_provider_clients()
        reader = ChainReader(clients)
        mapped = _load_gecko_mapped_pairs(args.subnet_limit)
        subnets = _live_probe_subnets(
            mapped, window_hours=args.window_hours, reader=reader
        )
        mode = "live"

    report = _report_from_subnets(
        subnets,
        window_hours=args.window_hours,
        git_sha=git_sha,
        mode=mode,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    warn_rows = report.get("warnings") or []
    summary: Dict[str, Any] = {
        "verdict": report["verdict"],
        "output": str(args.output),
        "warnings_count": len(warn_rows),
        "warning_netuids": sorted({w["netuid"] for w in warn_rows}),
    }
    print(json.dumps(summary, indent=2))
    verdict = report["verdict"]
    if verdict == "PASS":
        return 0
    if verdict == "FAIL":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
