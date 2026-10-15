#!/usr/bin/env python3
"""Reproducible GeckoTerminal pool orientation audit for config/price_pairs.json.

For each geckoterminal mapping, GET
  /api/v2/networks/{network}/pools/{pool}?include=base_token,quote_token
and compare base/quote token ids to subnet alpha (bittensor_{netuid}) and TAO
(bittensor_0).

Requests are paced at <=28/min (margin under GeckoTerminal's ~30/min cap).

Orientation classes:
  alpha_base_tao_quote — base_is_alpha should be true (alpha-in-TAO via currency=token, token=base)
  tao_base_alpha_quote   — base_is_alpha should be false (token=quote)
  unknown                — fail closed: remove base_is_alpha or set false; gecko tier skipped

Usage:
  PYTHONPATH=. python scripts/gecko_pool_orientation_audit.py
  PYTHONPATH=. python scripts/gecko_pool_orientation_audit.py --apply
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

GECKO_API = "https://api.geckoterminal.com/api/v2"
ROOT = Path(__file__).resolve().parents[1]
PAIRS_PATH = ROOT / "config" / "price_pairs.json"
ARTIFACT_JSON = ROOT / "docs" / "gecko-pool-orientation-audit.json"
ARTIFACT_MD = ROOT / "docs" / "gecko-pool-orientation-audit.md"
TAO_TOKEN_ID = "bittensor_0"
# Margin under GeckoTerminal ~30 req/min public cap.
MAX_CALLS_PER_MINUTE = 28
MIN_REQUEST_INTERVAL_S = 60.0 / MAX_CALLS_PER_MINUTE
DEFAULT_429_FALLBACK_S = 30.0
MAX_429_FALLBACK_S = 120.0


def _alpha_token_id(netuid: str) -> str:
    return f"bittensor_{netuid}"


def _parse_retry_after(resp: requests.Response) -> Optional[float]:
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(float(raw.strip()), 0.0)
    except ValueError:
        return None


def _retry_delay_seconds(resp: requests.Response, attempt: int) -> float:
    """Honor Retry-After on 429; bounded exponential fallback when absent."""
    parsed = _parse_retry_after(resp)
    if parsed is not None:
        return parsed
    return min(DEFAULT_429_FALLBACK_S * (2 ** attempt), MAX_429_FALLBACK_S)


class _RequestPacer:
    """Enforce minimum spacing between Gecko API calls."""

    def __init__(
        self,
        min_interval_s: float = MIN_REQUEST_INTERVAL_S,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._min_interval_s = min_interval_s
        self._monotonic = monotonic
        self._sleep = sleep
        self._last_at: Optional[float] = None

    def wait_turn(self) -> None:
        now = self._monotonic()
        if self._last_at is not None:
            elapsed = now - self._last_at
            remaining = self._min_interval_s - elapsed
            if remaining > 0:
                self._sleep(remaining)
        self._last_at = self._monotonic()


def _fetch_pool(
    network: str,
    pool: str,
    timeout: int = 30,
    *,
    max_attempts: int = 6,
    pacer: Optional[_RequestPacer] = None,
    sleep: Optional[Callable[[float], None]] = None,
    get: Optional[Callable[..., requests.Response]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if sleep is None:
        sleep = time.sleep
    if get is None:
        get = requests.get
    url = f"{GECKO_API}/networks/{network}/pools/{pool}"
    params = {"include": "base_token,quote_token"}
    last_err: Optional[str] = None
    for attempt in range(max_attempts):
        if pacer is not None:
            pacer.wait_turn()
        try:
            resp = get(url, params=params, timeout=timeout)
            if resp.status_code == 404:
                return None, "http_404"
            if resp.status_code == 429:
                last_err = "http_429_exhausted"
                delay = _retry_delay_seconds(resp, attempt)
                sleep(delay)
                continue
            resp.raise_for_status()
            return resp.json(), None
        except requests.HTTPError as exc:
            last_err = str(exc)
            break
        except Exception as exc:
            last_err = str(exc)
            break
    return None, last_err or "fetch_failed"


def _token_ids(payload: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    rel = payload.get("data", {}).get("relationships", {})
    base_id = (rel.get("base_token") or {}).get("data", {}).get("id")
    quote_id = (rel.get("quote_token") or {}).get("data", {}).get("id")
    name = payload.get("data", {}).get("attributes", {}).get("name")
    return base_id, quote_id, name


def _classify(
    netuid: str, base_id: Optional[str], quote_id: Optional[str]
) -> str:
    alpha = _alpha_token_id(netuid)
    if base_id == alpha and quote_id == TAO_TOKEN_ID:
        return "alpha_base_tao_quote"
    if base_id == TAO_TOKEN_ID and quote_id == alpha:
        return "tao_base_alpha_quote"
    return "unknown"


def _expected_base_is_alpha(orientation: str) -> Optional[bool]:
    if orientation == "alpha_base_tao_quote":
        return True
    if orientation == "tao_base_alpha_quote":
        return False
    return None


def audit_pairs(
    pairs: Dict[str, Any],
    *,
    pacer: Optional[_RequestPacer] = None,
    sleep: Optional[Callable[[float], None]] = None,
    get: Optional[Callable[..., requests.Response]] = None,
) -> Dict[str, Any]:
    if sleep is None:
        sleep = time.sleep
    if get is None:
        get = requests.get
    rows: List[Dict[str, Any]] = []
    pacer = pacer or _RequestPacer(sleep=sleep)

    def _sort_key(netuid: str) -> Tuple[int, str]:
        return (int(netuid), netuid) if str(netuid).isdigit() else (10**9, str(netuid))

    for netuid, info in sorted(pairs.items(), key=lambda kv: _sort_key(kv[0])):
        if not isinstance(info, dict):
            continue
        gt = info.get("geckoterminal")
        if not isinstance(gt, dict) or not gt.get("pool"):
            continue
        network = str(gt.get("network") or "")
        pool = str(gt.get("pool") or "")
        payload, err = _fetch_pool(
            network, pool, pacer=pacer, sleep=sleep, get=get
        )
        row: Dict[str, Any] = {
            "netuid": netuid,
            "network": network,
            "pool": pool,
            "expected_alpha_token_id": _alpha_token_id(netuid),
            "expected_tao_token_id": TAO_TOKEN_ID,
        }
        if err:
            row.update({"error": err, "orientation": "unknown", "base_is_alpha": None})
            rows.append(row)
            continue
        base_id, quote_id, pool_name = _token_ids(payload or {})
        orientation = _classify(netuid, base_id, quote_id)
        row.update(
            {
                "pool_name": pool_name,
                "base_token_id": base_id,
                "quote_token_id": quote_id,
                "orientation": orientation,
                "base_is_alpha": _expected_base_is_alpha(orientation),
                "configured_base_is_alpha": gt.get("base_is_alpha"),
            }
        )
        rows.append(row)

    ok = [r for r in rows if r.get("orientation") == "alpha_base_tao_quote"]
    inverted = [r for r in rows if r.get("orientation") == "tao_base_alpha_quote"]
    bad = [r for r in rows if r.get("orientation") == "unknown" or r.get("error")]
    return {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "gecko_mapping_count": len(rows),
        "alpha_base_tao_quote_count": len(ok),
        "tao_base_alpha_quote_count": len(inverted),
        "unknown_or_error_count": len(bad),
        "rows": rows,
    }


def apply_audit(pairs: Dict[str, Any], report: Dict[str, Any]) -> int:
    changed = 0
    by_netuid = {r["netuid"]: r for r in report.get("rows", [])}
    for netuid, info in pairs.items():
        if not isinstance(info, dict):
            continue
        gt = info.get("geckoterminal")
        if not isinstance(gt, dict):
            continue
        row = by_netuid.get(str(netuid))
        if not row:
            continue
        want = row.get("base_is_alpha")
        if want is True:
            if gt.get("base_is_alpha") is not True:
                gt["base_is_alpha"] = True
                changed += 1
        elif want is False:
            if gt.get("base_is_alpha") is not False:
                gt["base_is_alpha"] = False
                changed += 1
        else:
            if "base_is_alpha" in gt:
                del gt["base_is_alpha"]
                changed += 1
    return changed


def write_artifacts(report: Dict[str, Any]) -> None:
    ARTIFACT_JSON.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# GeckoTerminal pool orientation audit",
        "",
        f"- **Audited at (UTC):** {report.get('audited_at')}",
        f"- **Gecko mappings:** {report.get('gecko_mapping_count')}",
        f"- **alpha-base / TAO-quote:** {report.get('alpha_base_tao_quote_count')}",
        f"- **TAO-base / alpha-quote:** {report.get('tao_base_alpha_quote_count')}",
        f"- **Unknown or error:** {report.get('unknown_or_error_count')}",
        "",
        "Regenerate (paced <=28 Gecko calls/min):",
        "",
        "```bash",
        "PYTHONPATH=. python scripts/gecko_pool_orientation_audit.py",
        "```",
        "",
        "Machine-readable: `docs/gecko-pool-orientation-audit.json`.",
        "",
    ]
    bad = [r for r in report.get("rows", []) if r.get("orientation") != "alpha_base_tao_quote"]
    if bad:
        lines.append("## Exceptions")
        lines.append("")
        for r in bad:
            lines.append(
                f"- netuid **{r.get('netuid')}** pool `{r.get('pool')}`: "
                f"{r.get('orientation')} {r.get('error') or ''}".strip()
            )
    else:
        lines.append("All mapped pools are alpha-base / TAO-quote (`base_is_alpha: true`).")
    lines.append("")
    ARTIFACT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Update config/price_pairs.json base_is_alpha from audit",
    )
    parser.add_argument(
        "--pairs-path",
        type=Path,
        default=PAIRS_PATH,
        help="Path to price_pairs.json",
    )
    args = parser.parse_args()
    pairs = json.loads(args.pairs_path.read_text(encoding="utf-8"))
    report = audit_pairs(pairs)
    write_artifacts(report)
    print(json.dumps({k: report[k] for k in report if k != "rows"}, indent=2))
    if report.get("unknown_or_error_count"):
        print(
            f"WARNING: {report['unknown_or_error_count']} mapping(s) failed audit",
            file=sys.stderr,
        )
    if args.apply:
        if report.get("unknown_or_error_count"):
            print("Refusing --apply while audit has errors", file=sys.stderr)
            return 1
        n = apply_audit(pairs, report)
        args.pairs_path.write_text(json.dumps(pairs, indent=2) + "\n", encoding="utf-8")
        print(f"Applied {n} change(s) to {args.pairs_path}")
    return 0 if not report.get("unknown_or_error_count") else 1


if __name__ == "__main__":
    raise SystemExit(main())
