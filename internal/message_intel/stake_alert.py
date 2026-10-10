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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_HOTKEY = "5EAdPk767CtE8HhjhjAUNtLzd8vNm9Nm6fq9h3PGSL2VpYDc"
SS58_PREFIX = 42
_RAO = 1_000_000_000
_ALERT_THREAD: Optional[threading.Thread] = None
_ALERT_STOP = threading.Event()
STATE_PATH = os.environ.get("STAKE_ALERT_STATE_PATH", "data/stake_alert_state.json")

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


def _chain_rpc(client: Any, method: str, params: list) -> Any:
    """RPC helper: failures abort the stake scan (never confuse with empty data)."""
    call = getattr(client, "_call", None)
    if call is not None:
        try:
            result = call(method, params)
        except Exception as exc:
            raise StakeScanIncomplete(f"{method} failed: {exc}") from exc
    else:
        result = client._call_quiet(method, params)
    if method == "state_getKeysPaged" and (result is None or not isinstance(result, list)):
        raise StakeScanIncomplete(f"{method} failed")
    return result


def moving_price(client: Any, netuid: int) -> Optional[float]:
    """TAO-per-alpha price (SubtensorModule::SubnetMovingPrice, I96F32)."""
    key = "0x" + (
        twox128(b"SubtensorModule")
        + twox128(b"SubnetMovingPrice")
        + netuid.to_bytes(2, "little")
    ).hex()
    raw = client._call_quiet("state_getStorageAt", [key, None])
    if not raw:
        return None
    bits = bytes.fromhex(raw[2:] if raw.startswith("0x") else raw)
    if len(bits) < 16:
        return None
    return int.from_bytes(bits, "little", signed=True) / 2**32


def scan_hotkey_stakes(client: Any, hotkey_pub: bytes) -> Dict[str, int]:
    """Scan both Alpha stake maps for one hotkey.

    Keys are ``<map>:<coldkey_hex>:<netuid>`` mapped to shares in rao units.
    """
    out: Dict[str, int] = {}
    for map_name in _STAKE_MAPS:
        prefix = alpha_storage_prefix(map_name, hotkey_pub)
        prefix_hex = f"0x{prefix.hex()}"
        start: Optional[str] = None
        while True:
            keys = _chain_rpc(client, "state_getKeysPaged", [prefix_hex, 200, start, None])
            if not keys:
                break
            for k in keys:
                body = bytes.fromhex(k[2:])
                ck, netuid = _decode_alpha_key(body, len(prefix))
                rao = _decode_value(_chain_rpc(client, "state_getStorageAt", [k, None]))
                if rao:
                    out[f"{map_name}:{ck}:{netuid}"] = rao
            if len(keys) < 200:
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
    if not client.is_healthy():
        return None

    try:
        hotkey_pub = ss58_to_pubkey(os.environ.get("STAKE_ALERT_HOTKEY", "").strip() or DEFAULT_HOTKEY)
    except ValueError as exc:
        logger.error("stake alert: bad STAKE_ALERT_HOTKEY: %s", exc)
        return None

    try:
        current = scan_hotkey_stakes(client, hotkey_pub)
    except StakeScanIncomplete as exc:
        logger.warning("stake alert scan incomplete: %s", exc)
        return None

    prices: Dict[int, Optional[float]] = {}

    def price_lookup(netuid: int) -> Optional[float]:
        if netuid not in prices:
            try:
                prices[netuid] = moving_price(client, netuid)
            except Exception as exc:
                logger.warning("stake alert: price read SN%d failed: %s", netuid, exc)
                prices[netuid] = None
        return prices[netuid]

    state = _read_state()
    hotkey_hex = hotkey_pub.hex()
    if state.get("hotkey") != hotkey_hex:
        _write_state({"initialized": True, "baseline": current, "hotkey": hotkey_hex})
        logger.info(
            "stake alert baseline recorded for hotkey (%d entries)",
            len(current),
        )
        return {"baseline": True, "entries": len(current)}

    baseline = state.get("baseline") or {}
    if not state.get("initialized"):
        _write_state({"initialized": True, "baseline": current, "hotkey": hotkey_hex})
        logger.info("stake alert baseline recorded (%d entries)", len(current))
        return {"baseline": True, "entries": len(current)}

    alerts, new_baseline = compute_alerts(current, baseline, threshold_rao, price_lookup)
    if not alerts:
        if new_baseline != baseline:
            _write_state({"initialized": True, "baseline": new_baseline, "hotkey": hotkey_hex})
        return None

    block = client.get_current_block()
    message = format_stake_message(alerts, block)
    target = alert_chat_id()
    sent = False
    if target:
        from internal.message_intel.summary_bot import send_message

        chat: Any = int(target) if str(target).lstrip("-").isdigit() else target
        resp = send_message(chat, message, link_preview=False)
        sent = bool(resp.get("ok"))
        if not sent:
            logger.warning("stake alert send failed: %s", resp.get("error") or resp)
    if not sent:
        return {"alerts": len(alerts), "sent": False, "target": target}

    _write_state({"initialized": True, "baseline": new_baseline, "hotkey": hotkey_hex})
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
        _ALERT_STOP.wait(interval)


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
