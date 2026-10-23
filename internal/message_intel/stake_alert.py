"""Validator stake alert — pushes a Telegram note when accumulated stakes to a
hotkey cross a TAO threshold (SS-TG follow-on; direct-chain via Substrate RPC).

Detection polls the ``SubtensorModule::Alpha`` / ``AlphaV2`` storage maps
(key: hotkey, coldkey, netuid → rao) over plain HTTP JSON-RPC and diffs
against the last-alerted baseline, so repeated small stakes accumulate until
the threshold trips (4×25τ fires an 80τ alert).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

import requests

from internal.chain_price.rpc import classify_rpc_error
from internal.chain_rpc_errors import ChainRpcError

logger = logging.getLogger(__name__)

DEFAULT_HOTKEY = "5EAdPk767CtE8HhjhjAUNtLzd8vNm9Nm6fq9h3PGSL2VpYDc"
SS58_PREFIX = 42
_RAO = 1_000_000_000
_ALERT_THREAD: Optional[threading.Thread] = None
_ALERT_STOP = threading.Event()
STATE_PATH = os.environ.get("STAKE_ALERT_STATE_PATH", "data/stake_alert_state.json")
_KEYS_PAGE_SIZE = 200
_BATCH_RETRIES = 3
_DEFAULT_SCAN_DEADLINE_SECONDS = 120.0
_DEFAULT_STALE_SECONDS = 600.0
_DEFAULT_STALE_FAILURES = 3

_T = TypeVar("_T")

_STAKE_MAPS = ("Alpha", "AlphaV2")

# ---------------------------------------------------------------------------
# Minimal Substrate primitives (stdlib only — verified against canonical
# xxhash64 test vectors and live chain reads).
# ---------------------------------------------------------------------------

_P1 = 0x9E3779B185EBCA87
_P2 = 0xC2B2AE3D27D4EB4F
_P3 = 0x165667B19E3779F9
_P4 = 0x85EBCA77C2B2AE63
_P5 = 0x27D4EB2F165667C5
_M = 0xFFFFFFFFFFFFFFFF


def _rotl(x: int, r: int) -> int:
    return ((x << r) | (x >> (64 - r))) & _M


def _round(acc: int, inp: int) -> int:
    acc = (acc + (inp * _P2)) & _M
    acc = _rotl(acc, 31)
    return (acc * _P1) & _M


def _merge(acc: int, val: int) -> int:
    val = _round(0, val)
    acc ^= val
    return ((acc * _P1) + _P4) & _M


def xxh64(data: bytes, seed: int = 0) -> int:
    data = bytes(data)
    n = len(data)
    i = 0
    if n >= 32:
        v1 = (seed + _P1 + _P2) & _M
        v2 = (seed + _P2) & _M
        v3 = seed & _M
        v4 = (seed - _P1) & _M
        while i + 32 <= n:
            v1 = _round(v1, int.from_bytes(data[i:i + 8], "little"))
            v2 = _round(v2, int.from_bytes(data[i + 8:i + 16], "little"))
            v3 = _round(v3, int.from_bytes(data[i + 16:i + 24], "little"))
            v4 = _round(v4, int.from_bytes(data[i + 24:i + 32], "little"))
            i += 32
        h = (_rotl(v1, 1) + _rotl(v2, 7) + _rotl(v3, 12) + _rotl(v4, 18)) & _M
        for v in (v1, v2, v3, v4):
            h = _merge(h, v)
    else:
        h = (seed + _P5) & _M
    h = (h + n) & _M
    while i + 8 <= n:
        h ^= _round(0, int.from_bytes(data[i:i + 8], "little"))
        h = (_rotl(h, 27) * _P1 + _P4) & _M
        i += 8
    if i + 4 <= n:
        h ^= (int.from_bytes(data[i:i + 4], "little") * _P1) & _M
        h = (_rotl(h, 23) * _P2 + _P3) & _M
        i += 4
    # canonical xxHash64 processes every remaining byte 1..7 singly
    while i < n:
        h ^= (data[i] * _P5) & _M
        h = (_rotl(h, 11) * _P1) & _M
        i += 1
    h ^= h >> 33
    h = (h * _P2) & _M
    h ^= h >> 29
    h = (h * _P3) & _M
    h ^= h >> 32
    return h


def twox128(data: bytes) -> bytes:
    """Substrate TwoX128 — XXH64 with seed 0, then seed 1, each as LE u64."""
    return xxh64(data, 0).to_bytes(8, "little") + xxh64(data, 1).to_bytes(8, "little")


def _blake2_concat(key: bytes) -> bytes:
    """Substrate Blake2_128Concat hasher."""
    return hashlib.blake2b(key, digest_size=16).digest() + key


_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _base58_decode(s: str) -> bytes:
    n = 0
    for ch in s:
        idx = _ALPHABET.find(ch)
        if idx < 0:
            raise ValueError(f"invalid base58 character {ch!r}")
        n = n * 58 + idx
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + body


def _base58_encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _ALPHABET[r] + out
    pad = len(data) - len(data.lstrip(b"\x00"))
    return "1" * pad + out


def ss58_to_pubkey(ss58: str) -> bytes:
    """Decode an SS58 address to its 32-byte public key, verifying checksum."""
    raw = _base58_decode(ss58.strip())
    if len(raw) != 35:
        raise ValueError(f"unexpected SS58 length {len(raw)} (expected 35)")
    prefix, pubkey, checksum = raw[0], raw[1:33], raw[33:]
    expected = hashlib.blake2b(b"SS58PRE" + bytes([prefix]) + pubkey).digest()[:2]
    if checksum != expected:
        raise ValueError("SS58 checksum mismatch")
    return pubkey


def pubkey_to_ss58(pubkey: bytes) -> str:
    prefix = bytes([SS58_PREFIX])
    checksum = hashlib.blake2b(b"SS58PRE" + prefix + pubkey).digest()[:2]
    return _base58_encode(prefix + pubkey + checksum)


def alpha_storage_prefix(map_name: str, hotkey_pub: bytes) -> bytes:
    return (
        twox128(b"SubtensorModule")
        + twox128(map_name.encode())
        + _blake2_concat(hotkey_pub)
    )


def _decode_alpha_key(full_key: bytes, prefix_len: int) -> Tuple[str, int]:
    """(coldkey hex, netuid) from a full storage key."""
    body = full_key[prefix_len:]
    coldkey = body[16:48]  # blake2_128 checksum + 32-byte pubkey
    netuid = int.from_bytes(body[48:50], "little")
    return coldkey.hex(), netuid


def _decode_value(raw: Optional[str]) -> int:
    """Share amount in rao units from either map encoding.

    ``Alpha`` stores U64F64 fixed point (16 bytes, 64 frac bits); ``AlphaV2``
    stores SafeFloat (24 bytes: u128 mantissa × 10^i64 exponent).
    """
    if not raw:
        return 0
    b = bytes.fromhex(raw[2:] if raw.startswith("0x") else raw)
    if len(b) == 24:
        mantissa = int.from_bytes(b[:16], "little")
        exponent = int.from_bytes(b[16:24], "little", signed=True)
        if exponent >= 0:
            return mantissa * 10**exponent
        return mantissa // 10**(-exponent)
    return int.from_bytes(b, "little") // 2**64


class StakeScanIncomplete(Exception):
    """Any RPC read failed mid-scan; baseline must not be updated."""

    def __init__(
        self,
        message: str,
        *,
        rate_limited: bool = False,
        retry_after: Optional[float] = None,
    ):
        self.rate_limited = rate_limited
        self.retry_after = retry_after
        super().__init__(message)


def _http_retry_after(exc: BaseException) -> Optional[float]:
    if isinstance(exc, ChainRpcError) and exc.retry_after is not None:
        return exc.retry_after
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        raw = exc.response.headers.get("Retry-After")
        if raw:
            try:
                return max(0.0, float(raw))
            except ValueError:
                pass
    cause = exc.__cause__
    if cause is not None and cause is not exc:
        nested = _http_retry_after(cause)
        if nested is not None:
            return nested
    return None


def _stake_scan_incomplete(method: str, exc: BaseException) -> StakeScanIncomplete:
    rate_limited = classify_rpc_error(exc) == "rate_limited"
    return StakeScanIncomplete(
        f"{method} failed: {exc}",
        rate_limited=rate_limited,
        retry_after=_http_retry_after(exc),
    )


def _chain_rpc(client: Any, method: str, params: list) -> Any:
    """Single JSON-RPC attempt (``_call_typed`` — no nested 429 retries)."""
    typed = getattr(client, "_call_typed", None)
    if typed is None:
        raise StakeScanIncomplete(f"{method} failed: client missing _call_typed")
    try:
        result = typed(method, params)
    except Exception as exc:
        raise _stake_scan_incomplete(method, exc) from exc
    if method == "state_getKeysPaged" and (result is None or not isinstance(result, list)):
        raise StakeScanIncomplete(f"{method} failed")
    return result


def _chain_rpc_retry(
    client: Any,
    method: str,
    params: list,
    *,
    deadline: Optional[float] = None,
) -> Any:
    return _stake_rpc_retry(deadline, lambda: _chain_rpc(client, method, params))


def _scan_deadline_seconds() -> float:
    try:
        return float(os.environ.get("STAKE_ALERT_SCAN_DEADLINE_SECONDS", str(_DEFAULT_SCAN_DEADLINE_SECONDS)))
    except ValueError:
        return _DEFAULT_SCAN_DEADLINE_SECONDS


def _stale_threshold_seconds() -> float:
    try:
        return float(os.environ.get("STAKE_ALERT_STALE_SECONDS", str(_DEFAULT_STALE_SECONDS)))
    except ValueError:
        return _DEFAULT_STALE_SECONDS


def _stale_failure_count() -> int:
    try:
        return max(1, int(os.environ.get("STAKE_ALERT_STALE_FAILURES", str(_DEFAULT_STALE_FAILURES))))
    except ValueError:
        return _DEFAULT_STALE_FAILURES


def _parse_block_number(header: Dict[str, Any]) -> Optional[int]:
    num = header.get("number")
    if num is None:
        return None
    if isinstance(num, str):
        return int(num, 16)
    return int(num)


def finalized_head(client: Any, *, deadline: Optional[float] = None) -> Tuple[str, int]:
    """Finalized block hash and number for a consistent storage snapshot."""
    block_hash = _chain_rpc_retry(client, "chain_getFinalizedHead", [], deadline=deadline)
    if not block_hash:
        raise StakeScanIncomplete("chain_getFinalizedHead empty")
    header = _chain_rpc_retry(client, "chain_getHeader", [block_hash], deadline=deadline)
    if not isinstance(header, dict):
        raise StakeScanIncomplete("chain_getHeader failed")
    block = _parse_block_number(header)
    if block is None:
        raise StakeScanIncomplete("missing block number")
    return str(block_hash), block


def _storage_batch_values(client: Any, keys: List[str], at_hash: str) -> Dict[str, Optional[str]]:
    if not keys:
        return {}
    batch = _chain_rpc(client, "state_queryStorageAt", [keys, at_hash])
    if not batch or not isinstance(batch, list) or not isinstance(batch[0], dict):
        raise StakeScanIncomplete("state_queryStorageAt failed")
    changes = batch[0].get("changes") or []
    by_key: Dict[str, Optional[str]] = {row[0]: row[1] for row in changes if row}
    return {k: by_key.get(k) for k in keys}


def _batch_retry_sleep(attempt: int, exc: StakeScanIncomplete) -> float:
    if exc.rate_limited:
        base = min(60.0, 1.0 * (2 ** min(attempt - 1, 6)))
        if exc.retry_after is not None:
            waited = exc.retry_after if exc.retry_after > 0 else base
            return min(120.0, waited)
        return base
    return 0.25 * attempt


def _stake_rpc_retry(deadline: Optional[float], operation: Callable[[], _T]) -> _T:
    last: Optional[StakeScanIncomplete] = None
    attempt = 0
    while True:
        if deadline is not None and time.monotonic() > deadline:
            raise StakeScanIncomplete("scan deadline exceeded")
        try:
            return operation()
        except StakeScanIncomplete as exc:
            last = exc
            attempt += 1
            if exc.rate_limited:
                if attempt > _BATCH_RETRIES:
                    break
            elif attempt >= _BATCH_RETRIES:
                break
            sleep_for = _batch_retry_sleep(attempt, exc)
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if sleep_for > remaining:
                    raise StakeScanIncomplete("scan deadline exceeded") from exc
            time.sleep(sleep_for)
    raise last or StakeScanIncomplete("stake alert RPC failed")


def _storage_batch_values_retry(
    client: Any,
    keys: List[str],
    at_hash: str,
    *,
    deadline: Optional[float] = None,
) -> Dict[str, Optional[str]]:
    return _stake_rpc_retry(
        deadline,
        lambda: _storage_batch_values(client, keys, at_hash),
    )


def moving_price(
    client: Any,
    netuid: int,
    *,
    at_hash: Optional[str] = None,
    deadline: Optional[float] = None,
) -> Optional[float]:
    """TAO-per-alpha price (SubtensorModule::SubnetMovingPrice, I96F32)."""
    key = "0x" + (
        twox128(b"SubtensorModule")
        + twox128(b"SubnetMovingPrice")
        + netuid.to_bytes(2, "little")
    ).hex()
    if at_hash:
        raw = _storage_batch_values_retry(client, [key], at_hash, deadline=deadline).get(key)
    else:
        raw = client._call_quiet("state_getStorageAt", [key, None])
    if not raw:
        return None
    bits = bytes.fromhex(raw[2:] if raw.startswith("0x") else raw)
    if len(bits) < 16:
        return None
    return int.from_bytes(bits, "little", signed=True) / 2**32


def spot_price(
    client: Any,
    netuid: int,
    *,
    at_hash: str,
    deadline: Optional[float] = None,
) -> Optional[float]:
    """Spot TAO/alpha from SubnetTAO / SubnetAlphaIn at a pinned block."""
    from internal.chain_client import _decode_scale_u64, _hex_to_bytes
    from internal.chain_price.storage_keys import map_key_hex

    tao_key = map_key_hex(b"SubnetTAO", netuid)
    alpha_key = map_key_hex(b"SubnetAlphaIn", netuid)
    by_key = _storage_batch_values_retry(client, [tao_key, alpha_key], at_hash, deadline=deadline)

    def _u64(raw: Optional[str]) -> Optional[int]:
        if raw is None or raw == "0x" or raw == "0x00":
            return None
        try:
            return _decode_scale_u64(_hex_to_bytes(raw))
        except (TypeError, ValueError):
            return None

    tao_raw = _u64(by_key.get(tao_key))
    alpha_raw = _u64(by_key.get(alpha_key))
    if tao_raw is None or alpha_raw is None or alpha_raw == 0:
        return None
    return tao_raw / alpha_raw


def scan_hotkey_stakes(
    client: Any,
    hotkey_pub: bytes,
    *,
    at_hash: Optional[str] = None,
    deadline: Optional[float] = None,
) -> Dict[str, int]:
    """Scan both Alpha stake maps for one hotkey at a pinned finalized head.

    Keys are ``<map>:<coldkey_hex>:<netuid>`` mapped to shares in rao units.
    """
    if deadline is None:
        deadline = time.monotonic() + _scan_deadline_seconds()
    if at_hash is None:
        at_hash, _block = finalized_head(client, deadline=deadline)

    out: Dict[str, int] = {}
    for map_name in _STAKE_MAPS:
        prefix = alpha_storage_prefix(map_name, hotkey_pub)
        prefix_hex = f"0x{prefix.hex()}"
        start: Optional[str] = None
        while True:
            if time.monotonic() > deadline:
                raise StakeScanIncomplete("scan deadline exceeded")
            keys = _chain_rpc_retry(
                client,
                "state_getKeysPaged",
                [prefix_hex, _KEYS_PAGE_SIZE, start, at_hash],
                deadline=deadline,
            )
            if not keys:
                break
            values = _storage_batch_values_retry(client, keys, at_hash, deadline=deadline)
            for k in keys:
                body = bytes.fromhex(k[2:])
                ck, netuid = _decode_alpha_key(body, len(prefix))
                rao = _decode_value(values.get(k))
                if rao:
                    out[f"{map_name}:{ck}:{netuid}"] = rao
            if len(keys) < _KEYS_PAGE_SIZE:
                break
            start = keys[-1]
    return out


def compute_alerts(
    current: Dict[str, int],
    baseline: Dict[str, int],
    threshold_rao: int,
    price_lookup: Optional[Any] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Diff current stakes (shares in rao units) against the last-alerted baseline.

    Increases accumulate until the threshold trips (4×25τ fires an 80τ alert);
    decreases reset the baseline so re-stakes don't double-count. Values are
    shares in rao units; deltas convert to τ via the per-netuid moving price.
    When ``price_lookup`` is set, missing/zero/invalid prices skip alerting for
    that netuid and preserve its baseline until pricing is available.

    Returns (alerts, new_baseline) — alerts carry tau-valued ``delta_rao``.
    """
    def _tao_per_alpha(key: str) -> Optional[float]:
        if price_lookup is None:
            return 1.0
        netuid = int(key.split(":", 2)[2])
        price = price_lookup(netuid)
        if price is None or price <= 0:
            return None
        return price

    alerts: List[Dict[str, Any]] = []
    new_baseline: Dict[str, int] = {}
    for key, cur in sorted(current.items()):
        prev = baseline.get(key, 0)
        delta_raw = cur - prev
        if delta_raw > 0:
            price = _tao_per_alpha(key)
            if price is None:
                new_baseline[key] = prev
                continue
            delta_rao = int(delta_raw * price)
            if delta_rao >= threshold_rao:
                alerts.append({"key": key, "delta_rao": delta_rao, "total_rao": cur})
                new_baseline[key] = cur
            else:
                new_baseline[key] = prev
        elif delta_raw < 0:
            new_baseline[key] = cur
        else:
            new_baseline[key] = prev
    for key in baseline:
        if key not in current:
            new_baseline[key] = 0
    return alerts, new_baseline


def _short_ss58(coldkey_hex: str) -> str:
    try:
        full = pubkey_to_ss58(bytes.fromhex(coldkey_hex))
    except Exception:
        full = coldkey_hex
    return f"{full[:8]}…{full[-6:]}"


def format_stake_message(alerts: List[Dict[str, Any]], block: Optional[int]) -> str:
    """Telegram HTML note; digest form when several stakes land in one tick."""
    import html as _html

    lines: List[str] = []
    if len(alerts) > 1:
        total = sum(a["delta_rao"] for a in alerts) / _RAO
        lines.append(f"🐋 <b>{len(alerts)} new stakes to the Subnet Summer validator</b>")
        lines.append(f"{total:.1f}τ combined")
        lines.append("")
        for a in alerts:
            _, ck, _ = a["key"].split(":", 2)
            lines.append(f"• {a['delta_rao'] / _RAO:.1f}τ by {_short_ss58(ck)}")
    else:
        lines.append("🐋 <b>New stake to Subnet Summer validator</b>")
        for a in alerts:
            _, ck, _ = a["key"].split(":", 2)
            lines.append(
                f"{a['delta_rao'] / _RAO:.1f}τ delegated by "
                f"<code>{_html.escape(_short_ss58(ck))}</code>"
            )
    suffix = f" · head {block}" if block is not None else ""
    lines.append(f"Detected {datetime.now(timezone.utc).strftime('%H:%M UTC')}{suffix}")
    return "\n".join(lines)


def _read_state() -> Dict[str, Any]:
    try:
        raw = Path(STATE_PATH).read_text(encoding="utf-8")
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def stake_alert_last_ok_age_seconds(state: Optional[Dict[str, Any]] = None) -> Optional[float]:
    """Seconds since last successful stake scan (None when never ok or watcher disabled)."""
    data = state if state is not None else _read_state()
    last_ok = _parse_utc_iso(data.get("last_ok_at"))
    if last_ok is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - last_ok).total_seconds())


def stake_alert_failure_age_seconds(state: Optional[Dict[str, Any]] = None) -> Optional[float]:
    """Seconds since the first recorded failure in the current outage (legacy watchdog)."""
    data = state if state is not None else _read_state()
    first_at = _parse_utc_iso(data.get("first_failure_at"))
    if first_at is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - first_at).total_seconds())


def stake_alert_watchdog_stale(state: Optional[Dict[str, Any]] = None, *, enabled: Optional[bool] = None) -> bool:
    """Whether the stake watcher should be treated as stale for ops/readiness."""
    data = state if state is not None else _read_state()
    if enabled is None:
        enabled = stake_alert_enabled()
    if not enabled:
        return False
    threshold = _stale_threshold_seconds()
    age = stake_alert_last_ok_age_seconds(data)
    if age is not None and age > threshold:
        return True
    if data.get("last_ok_at"):
        return False
    failures = int(data.get("consecutive_failures") or 0)
    if failures < _stale_failure_count():
        return False
    failure_age = stake_alert_failure_age_seconds(data)
    if failure_age is None:
        return True
    return failure_age > threshold


def build_stake_alert_ops_summary() -> Dict[str, Any]:
    """Read-only watchdog view for readiness / metrics (no RPC)."""
    enabled = stake_alert_enabled()
    state = _read_state()
    age = stake_alert_last_ok_age_seconds(state)
    failure_age = stake_alert_failure_age_seconds(state)
    stale_threshold = _stale_threshold_seconds()
    stale = stake_alert_watchdog_stale(state, enabled=enabled)
    effective_age = age if age is not None else failure_age
    return {
        "enabled": enabled,
        "ops_telegram": stake_alert_ops_telegram_enabled(),
        "last_ok_at": state.get("last_ok_at"),
        "last_ok_block": state.get("last_ok_block"),
        "last_ok_age_seconds": effective_age,
        "failure_age_seconds": failure_age,
        "consecutive_failures": int(state.get("consecutive_failures") or 0),
        "first_failure_at": state.get("first_failure_at"),
        "last_skip_reason": state.get("last_skip_reason"),
        "stale": stale,
        "stale_threshold_seconds": stale_threshold,
    }


def _log_skip_once(state: Dict[str, Any], reason: str, detail: str = "") -> None:
    prev = state.get("last_skip_reason")
    if prev == reason:
        return
    msg = f"stake alert skip: {reason}"
    if detail:
        msg = f"{msg} ({detail})"
    logger.warning(msg)


def stake_alert_ops_telegram_enabled() -> bool:
    """Ops stale/recovery pushes (off by default — readiness/metrics still update)."""
    return os.environ.get("STAKE_ALERT_OPS_TELEGRAM", "off").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _maybe_ops_telegram(state: Dict[str, Any], *, recovered: bool) -> None:
    if not stake_alert_ops_telegram_enabled():
        return
    target = alert_chat_id()
    if not target:
        return
    from internal.message_intel.summary_bot import send_message

    chat: Any = int(target) if str(target).lstrip("-").isdigit() else target
    if recovered:
        if not state.get("ops_stale_notified"):
            return
        text = "✅ <b>Stake alert watcher recovered</b> — scans are healthy again."
        state["ops_stale_notified"] = False
    else:
        if state.get("ops_stale_notified"):
            return
        age = stake_alert_last_ok_age_seconds(state)
        if age is None:
            age = stake_alert_failure_age_seconds(state)
        mins = int((age or 0) // 60)
        reason = state.get("last_skip_reason") or "unknown"
        text = (
            f"⚠️ <b>Stake alert watcher stale</b> — no successful scan for ~{mins} min.\n"
            f"Last skip: <code>{reason}</code>"
        )
        state["ops_stale_notified"] = True
    try:
        send_message(chat, text, link_preview=False)
    except Exception as exc:
        logger.warning("stake alert ops telegram failed: %s", exc)
        if recovered:
            state["ops_stale_notified"] = True
        else:
            state["ops_stale_notified"] = False


def _record_skip(state: Dict[str, Any], reason: str, *, detail: str = "") -> Dict[str, Any]:
    _log_skip_once(state, reason, detail)
    state["last_skip_reason"] = reason
    state["consecutive_failures"] = int(state.get("consecutive_failures") or 0) + 1
    if not state.get("first_failure_at"):
        state["first_failure_at"] = _utcnow_iso()
    if stake_alert_watchdog_stale(state):
        _maybe_ops_telegram(state, recovered=False)
    return state


def _record_ok(state: Dict[str, Any], block: int) -> Dict[str, Any]:
    was_stale = bool(state.get("ops_stale_notified"))
    state["last_ok_at"] = _utcnow_iso()
    state["last_ok_block"] = block
    state["consecutive_failures"] = 0
    state["last_skip_reason"] = None
    state.pop("first_failure_at", None)
    if was_stale:
        _maybe_ops_telegram(state, recovered=True)
    return state


def _write_state(data: Dict[str, Any]) -> None:
    try:
        path = Path(STATE_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.warning("stake alert state write failed: %s", exc)


def alert_chat_id() -> Optional[str]:
    from internal.message_intel.trend_alert import alert_chat_id as _trend_chat

    return _trend_chat()


def check_stake_alerts(*, client: Any = None) -> Optional[Dict[str, Any]]:
    """One pass: scan, diff, alert, persist baseline."""
    try:
        threshold_rao = int(float(os.environ.get("STAKE_ALERT_MIN_TAO", "80")) * _RAO)
    except ValueError:
        threshold_rao = 80 * _RAO

    if client is None:
        from internal.chain_client import get_default_client

        client = get_default_client()

    state = _read_state()

    try:
        hotkey_pub = ss58_to_pubkey(os.environ.get("STAKE_ALERT_HOTKEY", "").strip() or DEFAULT_HOTKEY)
    except ValueError as exc:
        logger.error("stake alert: bad STAKE_ALERT_HOTKEY: %s", exc)
        return None

    deadline = time.monotonic() + _scan_deadline_seconds()
    try:
        at_hash, block = finalized_head(client, deadline=deadline)
    except StakeScanIncomplete as exc:
        state = _record_skip(state, "finalized_head", detail=str(exc))
        _write_state(state)
        return None

    try:
        current = scan_hotkey_stakes(client, hotkey_pub, at_hash=at_hash, deadline=deadline)
    except StakeScanIncomplete as exc:
        state = _record_skip(state, "incomplete_scan", detail=str(exc))
        _write_state(state)
        return None

    state = _record_ok(state, block)

    prices: Dict[int, Optional[float]] = {}
    price_sources: Dict[int, str] = {}

    def price_lookup(netuid: int) -> Optional[float]:
        if netuid not in prices:
            try:
                moving = moving_price(client, netuid, at_hash=at_hash, deadline=deadline)
                if moving is not None and moving > 0:
                    prices[netuid] = moving
                    price_sources[netuid] = "moving"
                else:
                    spot = spot_price(client, netuid, at_hash=at_hash, deadline=deadline)
                    prices[netuid] = spot
                    price_sources[netuid] = "spot" if spot else "missing"
                    if spot is not None:
                        logger.info("stake alert: SN%d price from spot (moving unavailable)", netuid)
                    else:
                        _log_skip_once(state, f"missing_price_sn{netuid}")
                        logger.warning("stake alert: missing price SN%d", netuid)
            except Exception as exc:
                logger.warning("stake alert: price read SN%d failed: %s", netuid, exc)
                prices[netuid] = None
                price_sources[netuid] = "error"
        return prices[netuid]

    hotkey_hex = hotkey_pub.hex()
    if state.get("hotkey") != hotkey_hex:
        state.update({"initialized": True, "baseline": current, "hotkey": hotkey_hex})
        _write_state(state)
        logger.info(
            "stake alert baseline recorded for hotkey (%d entries)",
            len(current),
        )
        return {"baseline": True, "entries": len(current)}

    baseline = state.get("baseline") or {}
    if not state.get("initialized"):
        state.update({"initialized": True, "baseline": current, "hotkey": hotkey_hex})
        _write_state(state)
        logger.info("stake alert baseline recorded (%d entries)", len(current))
        return {"baseline": True, "entries": len(current)}

    alerts, new_baseline = compute_alerts(current, baseline, threshold_rao, price_lookup)
    if not alerts:
        if new_baseline != baseline:
            state.update({"initialized": True, "baseline": new_baseline, "hotkey": hotkey_hex})
            _write_state(state)
        else:
            _write_state(state)
        return None

    message = format_stake_message(alerts, block)
    target = alert_chat_id()
    sent = False
    if target:
        from internal.message_intel.summary_bot import send_message

        chat: Any = int(target) if str(target).lstrip("-").isdigit() else target
        resp = send_message(chat, message, link_preview=False)
        sent = bool(resp.get("ok"))
        if not sent:
            state = _record_skip(state, "send_failure", detail=str(resp.get("error") or resp))
            _write_state(state)
            logger.warning("stake alert send failed: %s", resp.get("error") or resp)
    if not sent:
        return {"alerts": len(alerts), "sent": False, "target": target}

    state.update({"initialized": True, "baseline": new_baseline, "hotkey": hotkey_hex})
    _write_state(state)
    return {"alerts": len(alerts), "sent": True, "target": target}


def stake_alert_enabled() -> bool:
    from internal.run_mode import stage2_hop_mode

    if stage2_hop_mode():
        return False
    return os.environ.get("TELEGRAM_STAKE_ALERT", "off").strip().lower() in ("1", "true", "yes", "on")


def _alert_loop() -> None:
    try:
        interval = max(60, int(os.environ.get("STAKE_ALERT_INTERVAL_SECONDS", "300")))
    except ValueError:
        interval = 300
    logger.info("stake alert watcher started (interval=%ss)", interval)
    while not _ALERT_STOP.is_set():
        try:
            check_stake_alerts()
        except Exception as exc:
            logger.warning("stake alert tick failed: %s", exc)
        if _ALERT_STOP.wait(interval):
            break


def start_stake_alert_watcher() -> bool:
    """Start the periodic stake check when env-gated."""
    global _ALERT_THREAD
    if not stake_alert_enabled():
        logger.info("stake alert disabled (TELEGRAM_STAKE_ALERT=off)")
        return False
    if _ALERT_THREAD is not None and _ALERT_THREAD.is_alive():
        return True

    _ALERT_STOP.clear()
    _ALERT_THREAD = threading.Thread(target=_alert_loop, daemon=True, name="validator-stake-alert")
    _ALERT_THREAD.start()
    return True


def stop_stake_alert_watcher() -> None:
    global _ALERT_THREAD
    _ALERT_STOP.set()
    if _ALERT_THREAD is not None:
        _ALERT_THREAD.join(timeout=5)
        _ALERT_THREAD = None
    _ALERT_STOP.clear()
