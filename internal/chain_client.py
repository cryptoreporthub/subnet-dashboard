"""Lightweight HTTPS JSON-RPC client for Bittensor-compatible nodes.

Designed for Blockmachine's free public RPC (https://rpc.blockmachine.io)
but works with any Substrate/Bittensor JSON-RPC endpoint.

Primary data source for the dashboard's layered pipeline:
  Layer 1 (Primary):   Blockmachine RPC — real-time, free, no API key
  Layer 2 (Supp):      TaoStats API — derived metrics, 5 calls/min
  Layer 3 (Fallback):  TaoMarketCap — display metadata only

Swap volume detection uses pool reserve deltas:
  - TAO reserve up + Alpha reserve down = BUY (someone swapped TAO for Alpha)
  - TAO reserve down + Alpha reserve up = SELL (someone swapped Alpha for TAO)
This is more reliable than parsing raw SCALE events without chain metadata.
"""

import json
import logging
import os
import sqlite3
import struct
import threading
import time
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from internal import build_cost
from internal.metrics import CHAIN_RPC_REQUESTS_TOTAL

from internal.chain_rpc_errors import (
    ChainRpcError,
    PinnedBlockMismatch,
    classify_http_status,
    classify_jsonrpc_error,
    normalize_block_hash,
    storage_block_matches,
)

logger = logging.getLogger(__name__)

DEFAULT_RPC_URL = os.environ.get("BLOCKMACHINE_RPC_URL", "https://rpc.blockmachine.io")
DEFAULT_TIMEOUT = int(os.environ.get("BLOCKMACHINE_RPC_TIMEOUT_SECONDS", "10"))
DEFAULT_RETRIES = int(os.environ.get("BLOCKMACHINE_RPC_RETRIES", "3"))
DEFAULT_BACKOFF = [1.0, 2.0, 4.0]
HEALTH_TTL_SECONDS = 30.0
PRICE_SCALE = float(os.environ.get("BITTENSOR_PRICE_SCALE", "1e9"))
MAX_NETUIDS = 200
BATCH_DELAY = 0.15
VOLUME_DB_PATH = os.environ.get("VOLUME_DB_PATH", "data/volume_cache.db")

_RL_UNTIL: Dict[str, float] = {}
_RL_STEP: Dict[str, float] = {}
_RL_LOCK = threading.Lock()
_RL_DEFAULT_SECONDS = 60.0
_RL_MAX_SECONDS = 3600.0


def _normalize_endpoint(endpoint: str) -> str:
    return endpoint.rstrip("/")


def rate_limited_until(endpoint: str) -> float:
    """Monotonic deadline for endpoint-wide RPC cooldown (0 if none)."""
    ep = _normalize_endpoint(endpoint)
    with _RL_LOCK:
        return _RL_UNTIL.get(ep, 0.0)


def note_rate_limit(endpoint: str, retry_after: Optional[float] = None) -> float:
    """Record a 429; returns cooldown duration in seconds."""
    ep = _normalize_endpoint(endpoint)
    with _RL_LOCK:
        now = time.monotonic()
        until = _RL_UNTIL.get(ep, 0.0)
        if retry_after is not None:
            duration = min(max(0.0, float(retry_after)), _RL_MAX_SECONDS)
        elif now < until:
            return until - now
        else:
            step = _RL_STEP.get(ep, _RL_DEFAULT_SECONDS)
            duration = min(step, _RL_MAX_SECONDS)
            _RL_STEP[ep] = min(step * 2.0, _RL_MAX_SECONDS)
        _RL_UNTIL[ep] = max(until, now + duration)
        return duration


def _classify_alpha_price_probe_error(exc: BaseException) -> str:
    """Map RPC failures to live_subnets / universe outcome labels."""
    from internal.chain_price.rpc import classify_rpc_error

    if isinstance(exc, ChainRpcError) and exc.kind == "rate_limited":
        if "cooldown" in str(exc).lower():
            return "cooldown_skip"
    labeled = classify_rpc_error(exc)
    if labeled in ("timeout", "connection", "parse", "rate_limited", "rpc_error"):
        return labeled
    return "rpc_error"


def _parse_retry_after_header(response: requests.Response) -> Optional[float]:
    raw = (response.headers.get("Retry-After") or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return float(raw)
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, when.timestamp() - time.time())


def _metric_endpoint(endpoint: str | None) -> str:
    """Hostname-only label for metrics/logs; never returns query/path secrets."""
    if not endpoint:
        return "unknown"
    try:
        parsed = urlparse(_normalize_endpoint(endpoint))
    except ValueError:
        return "unknown"
    if parsed.hostname:
        return parsed.hostname
    if parsed.netloc and "@" not in parsed.netloc:
        host = parsed.netloc.split(":")[0]
        if host:
            return host
    return "unknown"


def _record_chain_rpc(endpoint: str, method: str, outcome: str) -> None:
    CHAIN_RPC_REQUESTS_TOTAL.labels(
        endpoint=_metric_endpoint(endpoint),
        method=method,
        outcome=outcome,
    ).inc()


def _clear_rate_limit_step(endpoint: str) -> None:
    ep = _normalize_endpoint(endpoint)
    with _RL_LOCK:
        _RL_STEP.pop(ep, None)


def _init_volume_db():
    os.makedirs(os.path.dirname(VOLUME_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(VOLUME_DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS pool_snapshots (
            netuid INTEGER,
            timestamp TEXT,
            tao_reserve REAL,
            alpha_reserve REAL,
            PRIMARY KEY (netuid, timestamp)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS swap_volume (
            netuid INTEGER,
            timestamp TEXT,
            buys INTEGER DEFAULT 0,
            sells INTEGER DEFAULT 0,
            buy_volume_tao REAL DEFAULT 0.0,
            sell_volume_tao REAL DEFAULT 0.0,
            PRIMARY KEY (netuid, timestamp)
        )
    """)
    conn.commit()
    conn.close()


def _decode_scale_compact(raw):
    if not raw:
        return 0, 0
    first = raw[0]
    mode = first & 0b11
    if mode == 0b00:
        return (first >> 2), 1
    elif mode == 0b01:
        if len(raw) < 2:
            return 0, 1
        return ((first >> 2) | (raw[1] << 6)), 2
    elif mode == 0b10:
        if len(raw) < 4:
            return 0, 1
        val = (first >> 2) | (raw[1] << 6) | (raw[2] << 14) | (raw[3] << 22)
        return val, 4
    else:
        byte_len = (first >> 2) + 4
        if len(raw) < 1 + byte_len:
            return 0, 1
        val = 0
        for i in range(byte_len):
            val |= raw[1 + i] << (8 * i)
        return val, 1 + byte_len


def _decode_dynamic_info_pool(raw):
    """Decode current Subtensor DynamicInfo enough to read pool reserves.

    Current nodes return SCALE-encoded ``Option<DynamicInfo>`` as a byte
    array. Older nodes exposed the same values through ``Swap_get_pool``,
    which is no longer exported by the runtime used by the live RPC.
    """
    if isinstance(raw, str):
        raw = _hex_to_bytes(raw)
    if not isinstance(raw, (bytes, bytearray, list, tuple)) or not raw:
        return None
    data = list(raw)
    if data[0] == 0:
        return None
    if data[0] != 1:
        return None

    def compact_at(offset):
        value, consumed = _decode_scale_compact(data[offset:])
        if not consumed:
            raise ValueError("invalid compact value")
        return value, offset + consumed

    def compact_vec_at(offset):
        length, offset = compact_at(offset)
        values = []
        for _ in range(length):
            value, offset = compact_at(offset)
            values.append(value)
        return values, offset

    try:
        offset = 1
        netuid, offset = compact_at(offset)
        # AccountId is [u8; 32] for Bittensor hotkeys and coldkeys.
        offset += 64
        if offset > len(data):
            return None
        subnet_name, offset = compact_vec_at(offset)
        token_symbol, offset = compact_vec_at(offset)
        # tempo, last_step, blocks_since_last_step, emission
        for _ in range(4):
            _, offset = compact_at(offset)
        alpha_in, offset = compact_at(offset)
        alpha_out, offset = compact_at(offset)
        tao_in, offset = compact_at(offset)
    except (IndexError, TypeError, ValueError):
        return None

    if tao_in <= 0:
        return None
    tao_reserve = tao_in / 1e9
    alpha_reserve = alpha_in / 1e9
    alpha_price = tao_reserve / alpha_reserve if alpha_reserve > 0 else 0.0
    return {
        "netuid": int(netuid),
        "name": bytes(subnet_name).decode("utf-8", errors="replace") or f"SN{netuid}",
        "symbol": bytes(token_symbol).decode("utf-8", errors="replace"),
        "total_tao": round(tao_reserve, 6),
        "total_alpha": round(alpha_reserve, 6),
        "liquidity": round(tao_reserve + (alpha_reserve * alpha_price), 6),
        "tao_reserve_raw": int(tao_in),
        "alpha_reserve_raw": int(alpha_in),
        "alpha_out": int(alpha_out),
    }


def _decode_scale_u128(raw):
    if len(raw) < 16:
        padded = raw + b'\x00' * (16 - len(raw))
    else:
        padded = raw[:16]
    return int.from_bytes(padded, 'little')


def _decode_scale_u64(raw):
    if len(raw) < 8:
        padded = raw + b'\x00' * (8 - len(raw))
    else:
        padded = raw[:8]
    return int.from_bytes(padded, 'little')


def _decode_scale_u32(raw):
    if len(raw) < 4:
        padded = raw + b'\x00' * (4 - len(raw))
    else:
        padded = raw[:4]
    return int.from_bytes(padded, 'little')


def _hex_to_bytes(hex_str):
    if hex_str.startswith("0x") or hex_str.startswith("0X"):
        hex_str = hex_str[2:]
    return bytes.fromhex(hex_str)


def _encode_netuid_arg(netuid):
    return "0x" + struct.pack("<H", netuid).hex()


def _decode_storage_u64(raw: Any) -> Optional[int]:
    if raw is None or raw == "0x" or raw == "0x00":
        return None
    try:
        return _decode_scale_u64(_hex_to_bytes(raw))
    except (TypeError, ValueError):
        return None


def _storage_chunk_netuids(netuids: List[int], chunk_size: int) -> List[List[int]]:
    size = max(1, chunk_size)
    return [netuids[i : i + size] for i in range(0, len(netuids), size)]


def _row_from_subnet_reserves(netuid: int, tao_raw: int, alpha_raw: int, source: str) -> dict:
    tao_reserve = tao_raw / 1e9
    alpha_reserve = alpha_raw / 1e9
    price = tao_reserve / alpha_reserve if alpha_reserve > 0 else 0.0
    return {
        "netuid": netuid,
        "name": f"SN{netuid}",
        "price": price,
        "source": source,
        "liquidity": round(tao_reserve + (alpha_reserve * price), 6),
        "total_tao": round(tao_reserve, 6),
        "total_alpha": round(alpha_reserve, 6),
        "taoLiquidity": round(tao_reserve, 6),
        "tao_reserve_raw": int(tao_raw),
        "alpha_reserve_raw": int(alpha_raw),
    }


def _normalize_block_hash(block_hash: str) -> str:
    return normalize_block_hash(block_hash)


def _timed_post(endpoint: str, payload: Dict[str, Any], timeout: float) -> requests.Response:
    """One RPC HTTP attempt, timed for the active snapshot build."""
    started = time.perf_counter()
    try:
        return requests.post(
            endpoint,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
    finally:
        build_cost.record("rpc", time.perf_counter() - started)


class ChainClient:
    def __init__(
        self,
        endpoint=DEFAULT_RPC_URL,
        timeout=DEFAULT_TIMEOUT,
        retries=DEFAULT_RETRIES,
        backoff=None,
        *,
        init_volume_db: bool = True,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff or DEFAULT_BACKOFF
        self._last_health_check = 0.0
        self._healthy = True
        if init_volume_db:
            _init_volume_db()

    def _call(self, method, params=None):
        params = params or []
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": int(time.time() * 1000) % 2147483647,
        }
        last_error = None
        for attempt in range(self.retries + 1):
            try:
                if time.monotonic() < rate_limited_until(self.endpoint):
                    _record_chain_rpc(self.endpoint, method, "cooldown_skip")
                    raise ChainRpcError("rate_limited", "cooldown")
                response = _timed_post(self.endpoint, payload, self.timeout)
                if response.status_code == 429:
                    note_rate_limit(self.endpoint, _parse_retry_after_header(response))
                    _record_chain_rpc(self.endpoint, method, "rate_limited")
                    raise ChainRpcError(
                        "rate_limited", "HTTP 429", code=429, http_status=429
                    )
                response.raise_for_status()
                data = response.json()
                if "error" in data:
                    _record_chain_rpc(self.endpoint, method, "error")
                    raise RuntimeError(data["error"])
                _record_chain_rpc(self.endpoint, method, "ok")
                _clear_rate_limit_step(self.endpoint)
                return data.get("result")
            except ChainRpcError as exc:
                if exc.kind == "rate_limited":
                    raise
                last_error = exc
                _record_chain_rpc(self.endpoint, method, "error")
            except Exception as exc:
                last_error = exc
                _record_chain_rpc(self.endpoint, method, "error")
                sleep_for = self.backoff[min(attempt, len(self.backoff) - 1)]
                logger.debug("RPC %s attempt %d failed: %s", method, attempt, exc)
                if attempt < self.retries:
                    time.sleep(sleep_for)
        raise last_error or RuntimeError(f"RPC call to {method} failed")

    def _call_typed(self, method, params=None):
        """JSON-RPC with classified errors; retries only network / HTTP 5xx (not 429)."""
        params = params or []
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": int(time.time() * 1000) % 2147483647,
        }
        last_error: Optional[BaseException] = None
        deadline_mono = getattr(self, "_rpc_deadline_mono", None)
        for attempt in range(self.retries + 1):
            try:
                if deadline_mono is not None:
                    remaining = deadline_mono - time.monotonic()
                    if remaining <= 0:
                        raise ChainRpcError("timeout", "rpc deadline exceeded")
                    self.timeout = min(float(self.timeout), max(0.01, remaining))
                if time.monotonic() < rate_limited_until(self.endpoint):
                    _record_chain_rpc(self.endpoint, method, "cooldown_skip")
                    raise ChainRpcError("rate_limited", "cooldown")
                response = _timed_post(self.endpoint, payload, self.timeout)
                if response.status_code == 429:
                    retry_after = _parse_retry_after_header(response)
                    note_rate_limit(self.endpoint, retry_after)
                    _record_chain_rpc(self.endpoint, method, "rate_limited")
                    raise ChainRpcError(
                        "rate_limited",
                        "HTTP 429",
                        code=429,
                        retry_after=retry_after,
                        http_status=429,
                    )
                if response.status_code >= 500:
                    _record_chain_rpc(self.endpoint, method, "error")
                    last_error = ChainRpcError(
                        classify_http_status(response.status_code),
                        f"HTTP {response.status_code}",
                        code=response.status_code,
                    )
                    sleep_for = self.backoff[min(attempt, len(self.backoff) - 1)]
                    if attempt < self.retries:
                        time.sleep(sleep_for)
                        continue
                    raise last_error
                # 408 (request timeout) is transient and falls through to the retry path below.
                if 400 <= response.status_code < 500 and response.status_code != 408:
                    # Other client errors are not transient; raise without retrying.
                    _record_chain_rpc(self.endpoint, method, "error")
                    raise ChainRpcError(
                        classify_http_status(response.status_code),
                        f"HTTP {response.status_code}",
                        code=response.status_code,
                    )
                response.raise_for_status()
                try:
                    data = response.json()
                except json.JSONDecodeError as exc:
                    _record_chain_rpc(self.endpoint, method, "error")
                    raise ChainRpcError("parse", str(exc))
                if "error" in data:
                    kind = classify_jsonrpc_error(data["error"])
                    err = data["error"]
                    code = err.get("code") if isinstance(err, dict) else None
                    _record_chain_rpc(self.endpoint, method, "error")
                    raise ChainRpcError(
                        kind,
                        str(err.get("message") if isinstance(err, dict) else err),
                        code=code,
                    )
                _record_chain_rpc(self.endpoint, method, "ok")
                _clear_rate_limit_step(self.endpoint)
                return data.get("result")
            except ChainRpcError:
                raise
            except requests.exceptions.Timeout as exc:
                _record_chain_rpc(self.endpoint, method, "error")
                raise ChainRpcError("timeout", str(exc))
            except requests.exceptions.ConnectionError as exc:
                _record_chain_rpc(self.endpoint, method, "error")
                raise ChainRpcError("connection", str(exc))
            except requests.RequestException as exc:
                last_error = exc
                _record_chain_rpc(self.endpoint, method, "error")
                sleep_for = self.backoff[min(attempt, len(self.backoff) - 1)]
                logger.debug("typed RPC %s attempt %d failed: %s", method, attempt, exc)
                if attempt < self.retries:
                    if deadline_mono is not None and time.monotonic() + sleep_for > deadline_mono:
                        raise ChainRpcError("timeout", "rpc deadline exceeded before retry")
                    time.sleep(sleep_for)
            except Exception as exc:
                last_error = exc
                _record_chain_rpc(self.endpoint, method, "error")
                sleep_for = self.backoff[min(attempt, len(self.backoff) - 1)]
                if attempt < self.retries:
                    if deadline_mono is not None and time.monotonic() + sleep_for > deadline_mono:
                        raise ChainRpcError("timeout", "rpc deadline exceeded before retry")
                    time.sleep(sleep_for)
        if isinstance(last_error, ChainRpcError):
            raise last_error
        raise ChainRpcError("rpc_error", str(last_error or f"RPC call to {method} failed"))

    def get_block_hash(self, number: Optional[int] = None) -> str:
        params = [number] if number is not None else []
        result = self._call_typed("chain_getBlockHash", params)
        if not result:
            raise ChainRpcError("invalid", "empty block hash")
        return str(result)

    def get_block_header(self, block_hash: str) -> Dict[str, Any]:
        header = self._call_typed("chain_getHeader", [block_hash])
        if not isinstance(header, dict):
            raise ChainRpcError("invalid", "missing header")
        return header

    def get_block_ts_ms(self, block_hash: str) -> Optional[int]:
        from internal.chain_price.storage_keys import timestamp_now_key_hex

        batch = self.query_storage_at([timestamp_now_key_hex()], block_hash)
        if not batch:
            return None
        changes = batch[0].get("changes") if isinstance(batch[0], dict) else None
        if not changes:
            return None
        key = timestamp_now_key_hex()
        for row in changes:
            if row and row[0] == key:
                raw = row[1]
                if raw is None or raw == "0x":
                    return None
                return _decode_scale_u64(_hex_to_bytes(raw))
        return None

    def query_storage_at(self, keys: List[str], at_hash: str) -> List[Dict[str, Any]]:
        batch = self._call_typed("state_queryStorageAt", [keys, at_hash])
        if not batch:
            raise ChainRpcError("invalid", "empty queryStorageAt")
        entry = batch[0]
        if not isinstance(entry, dict):
            raise ChainRpcError("invalid", "invalid queryStorageAt entry")
        if not storage_block_matches(entry, at_hash):
            got = entry.get("block")
            if not got:
                raise ChainRpcError("invalid", "queryStorageAt entry missing block")
            raise PinnedBlockMismatch(at_hash, str(got))
        return batch

    def get_keys_paged(
        self,
        prefix: str,
        count: int,
        start: Optional[str],
        at_hash: str,
    ) -> List[str]:
        result = self._call_typed("state_getKeysPaged", [prefix, count, start, at_hash])
        if result is None:
            return []
        return list(result)

    def get_alpha_price_at(self, netuid: int, at_hash: str) -> Tuple[Optional[float], str]:
        try:
            raw = self._call_typed("swap_currentAlphaPrice", [netuid, at_hash])
            if raw is None:
                return None, "no_price"
            return float(raw) / PRICE_SCALE, "ok"
        except ChainRpcError as exc:
            if exc.kind == "archive_miss":
                return None, "archive_miss"
            if exc.kind == "unknown_block":
                return None, "invalid"
            if exc.kind == "rate_limited":
                return None, "rate_limited"
            return None, "rpc_error"

    def _call_quiet(self, method, params=None):
        try:
            return self._call(method, params)
        except Exception:
            return None

    def is_healthy(self):
        now = time.time()
        if now - self._last_health_check < HEALTH_TTL_SECONDS:
            return self._healthy
        try:
            result = self._call("chain_getBlockHash", [0])
            self._healthy = bool(result)
        except Exception as exc:
            logger.debug("RPC health check failed: %s", exc)
            self._healthy = False
        self._last_health_check = now
        return self._healthy

    @property
    def degraded(self):
        return not self._healthy

    def get_alpha_price_probed(self, netuid) -> Tuple[Optional[float], str]:
        """Typed alpha price fetch for membership and live-batch consumers.

        Returns (price, outcome) where outcome is ``ok``, ``no_price`` (successful
        null/empty), or ``rpc_error`` (transport/JSON-RPC/parse failure).
        """
        try:
            result = self._call("swap_currentAlphaPrice", [netuid])
            if result is None:
                return None, "no_price"
            return float(result) / PRICE_SCALE, "ok"
        except Exception as exc:
            outcome = _classify_alpha_price_probe_error(exc)
            logger.debug(
                "swap_currentAlphaPrice failed for netuid %s (%s): %s",
                netuid,
                outcome,
                exc,
            )
            return None, outcome

    def get_alpha_price(self, netuid):
        price, _outcome = self.get_alpha_price_probed(netuid)
        return price

    def get_all_netuids(self):
        if not self.is_healthy():
            return []
        try:
            result = self._call_quiet("subnet_getN", [])
            if result is not None:
                total = int(result)
                netuids = list(range(min(total, MAX_NETUIDS)))
                logger.info("get_all_netuids: %d via subnet_getN", len(netuids))
                return netuids
        except Exception:
            pass
        try:
            result = self._call_quiet("state_call", ["SubtensorModule_get_total_subnets", "0x"])
            if result and result != "0x":
                raw = _hex_to_bytes(result)
                total = _decode_scale_u32(raw)
                netuids = list(range(min(total, MAX_NETUIDS)))
                logger.info("get_all_netuids: %d via state_call", len(netuids))
                return netuids
        except Exception:
            pass
        netuids = []
        for n in range(MAX_NETUIDS):
            try:
                price = self.get_alpha_price(n)
                if price is not None:
                    netuids.append(n)
                time.sleep(BATCH_DELAY)
            except Exception:
                if netuids and n - netuids[-1] > 5:
                    break
        logger.info("get_all_netuids: %d via probe", len(netuids))
        return netuids

    def get_subnet_stake(self, netuid):
        if not self.is_healthy():
            return None
        try:
            result = self._call_quiet("state_call", [
                "SubtensorModule_get_total_stake_for_subnet",
                _encode_netuid_arg(netuid),
            ])
            if result and result != "0x":
                raw = _hex_to_bytes(result)
                total_stake = _decode_scale_u128(raw)
                stake_tao = total_stake / 1e9
                return {"netuid": netuid, "total_stake": round(stake_tao, 4), "stake": round(stake_tao, 4)}
        except Exception as exc:
            logger.debug("get_subnet_stake failed for netuid %d: %s", netuid, exc)
        return None

    def get_pool_state(self, netuid):
        if not self.is_healthy():
            return None
        try:
            raw = self._call_quiet("subnetInfo_getDynamicInfo", [int(netuid)])
            pool = _decode_dynamic_info_pool(raw)
            if pool:
                tao = float(pool["total_tao"])
                alpha = float(pool["total_alpha"])
                return {
                    **pool,
                    "netuid": int(netuid),
                    "root_prop": round(alpha / (tao + alpha), 4) if (tao + alpha) > 0 else 0,
                }
        except Exception as exc:
            logger.debug("get_pool_state failed for netuid %d: %s", netuid, exc)
        return None

    def get_subnet_emission(self, netuid):
        if not self.is_healthy():
            return None
        try:
            result = self._call_quiet("state_call", [
                "SubtensorModule_get_emission_value", _encode_netuid_arg(netuid),
            ])
            if result and result != "0x":
                raw = _hex_to_bytes(result)
                emission_raw = _decode_scale_u64(raw)
                emission_tao_day = (emission_raw / 1e9) * 7200
                return round(emission_tao_day, 4)
        except Exception as exc:
            logger.debug("get_subnet_emission failed for netuid %d: %s", netuid, exc)
        return None

    def get_current_block(self):
        try:
            result = self._call("chain_getBlockHash", [])
            if result:
                header = self._call_quiet("chain_getHeader", [result])
                if header and isinstance(header, dict):
                    num = header.get("number")
                    if num:
                        return int(num, 16) if isinstance(num, str) else int(num)
        except Exception as exc:
            logger.debug("get_current_block failed: %s", exc)
        return None

    # ------------------------------------------------------------------
    # Swap volume detection via pool reserve deltas
    # ------------------------------------------------------------------

    def get_swap_volume(self, netuid):
        """Detect buy/sell volume by comparing pool reserves to previous snapshot.

        - Buy: TAO in, Alpha out (tao_reserve up, alpha_reserve down)
        - Sell: TAO out, Alpha in (tao_reserve down, alpha_reserve up)
        - Both up/down: LP operation (skipped)
        """
        if not self.is_healthy():
            return self._empty_volume()

        current_pool = self.get_pool_state(netuid)
        if not current_pool:
            return self._empty_volume()

        current_tao = current_pool.get("tao_reserve_raw", 0) or current_pool.get("total_tao", 0)
        current_alpha = current_pool.get("alpha_reserve_raw", 0) or current_pool.get("total_alpha", 0)

        if current_tao > 1e12:
            current_tao_tao = current_tao / 1e9
            current_alpha_tao = current_alpha / 1e9
        else:
            current_tao_tao = current_tao
            current_alpha_tao = current_alpha

        prev = self._get_last_pool_snapshot(netuid)

        buys = 0
        sells = 0
        buy_vol = 0.0
        sell_vol = 0.0

        if prev:
            prev_tao = prev.get("tao_reserve", 0)
            prev_alpha = prev.get("alpha_reserve", 0)
            tao_delta = current_tao_tao - prev_tao
            alpha_delta = current_alpha_tao - prev_alpha

            if tao_delta > 0.0001 and alpha_delta < -0.0001:
                buys = 1
                buy_vol = abs(tao_delta)
            elif tao_delta < -0.0001 and alpha_delta > 0.0001:
                sells = 1
                sell_vol = abs(tao_delta)

        self._store_pool_snapshot(netuid, current_tao_tao, current_alpha_tao)

        if buys > 0 or sells > 0:
            self._store_volume(netuid, buys, sells, buy_vol, sell_vol)

        cumulative = self._get_cumulative_volume_24h(netuid)

        return {
            "buys": buys,
            "sells": sells,
            "buy_volume_tao": round(buy_vol, 6),
            "sell_volume_tao": round(sell_vol, 6),
            "buys_24h": cumulative.get("buys_24h", 0),
            "sells_24h": cumulative.get("sells_24h", 0),
            "buy_volume_24h": round(cumulative.get("buy_volume_24h", 0.0), 6),
            "sell_volume_24h": round(cumulative.get("sell_volume_24h", 0.0), 6),
            "current_tao_reserve": round(current_tao_tao, 4),
            "current_alpha_reserve": round(current_alpha_tao, 4),
        }

    def _empty_volume(self):
        return {
            "buys": 0, "sells": 0, "buy_volume_tao": 0.0, "sell_volume_tao": 0.0,
            "buys_24h": 0, "sells_24h": 0, "buy_volume_24h": 0.0, "sell_volume_24h": 0.0,
        }

    def _store_pool_snapshot(self, netuid, tao_reserve, alpha_reserve):
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        conn = sqlite3.connect(VOLUME_DB_PATH)
        c = conn.cursor()
        c.execute("""
            INSERT OR REPLACE INTO pool_snapshots (netuid, timestamp, tao_reserve, alpha_reserve)
            VALUES (?, ?, ?, ?)
        """, (netuid, now, tao_reserve, alpha_reserve))
        conn.commit()
        conn.close()

    def _get_last_pool_snapshot(self, netuid):
        conn = sqlite3.connect(VOLUME_DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT timestamp, tao_reserve, alpha_reserve
            FROM pool_snapshots WHERE netuid = ?
            ORDER BY timestamp DESC LIMIT 1
        """, (netuid,))
        row = c.fetchone()
        conn.close()
        if row:
            return {"timestamp": row[0], "tao_reserve": row[1], "alpha_reserve": row[2]}
        return None

    def _store_volume(self, netuid, buys, sells, buy_vol, sell_vol):
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        conn = sqlite3.connect(VOLUME_DB_PATH)
        c = conn.cursor()
        c.execute("""
            INSERT OR REPLACE INTO swap_volume
            (netuid, timestamp, buys, sells, buy_volume_tao, sell_volume_tao)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (netuid, now, buys, sells, buy_vol, sell_vol))
        conn.commit()
        conn.close()

    def _get_cumulative_volume_24h(self, netuid):
        cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 86400))
        conn = sqlite3.connect(VOLUME_DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT COALESCE(SUM(buys), 0), COALESCE(SUM(sells), 0),
                   COALESCE(SUM(buy_volume_tao), 0), COALESCE(SUM(sell_volume_tao), 0)
            FROM swap_volume WHERE netuid = ? AND timestamp >= ?
        """, (netuid, cutoff))
        row = c.fetchone()
        conn.close()
        if row:
            return {"buys_24h": row[0], "sells_24h": row[1],
                    "buy_volume_24h": row[2], "sell_volume_24h": row[3]}
        return {"buys_24h": 0, "sells_24h": 0, "buy_volume_24h": 0.0, "sell_volume_24h": 0.0}

    def get_all_subnet_data(self, netuids=None):
        if not self.is_healthy():
            return []
        if netuids is None:
            netuids = self.get_all_netuids()
        if not netuids:
            return []
        subnets = []
        for netuid in netuids:
            try:
                price = self.get_alpha_price(netuid)
                stake = self.get_subnet_stake(netuid)
                pool = self.get_pool_state(netuid)
                emission = self.get_subnet_emission(netuid)
                volume = self.get_swap_volume(netuid)
                subnet = {
                    "netuid": netuid, "name": f"SN{netuid}", "price": price or 0.0,
                    "stake": stake.get("stake", 0) if stake else 0,
                    "total_stake": stake.get("total_stake", 0) if stake else 0,
                    "emission": emission or 0.0,
                    "liquidity": pool.get("liquidity", 0) if pool else 0,
                    "total_tao": pool.get("total_tao", 0) if pool else 0,
                    "total_alpha": pool.get("total_alpha", 0) if pool else 0,
                    "root_prop": pool.get("root_prop", 0) if pool else 0,
                    "buys_24hr": volume.get("buys_24h", 0),
                    "sells_24hr": volume.get("sells_24h", 0),
                    "buy_volume_24h": volume.get("buy_volume_24h", 0.0),
                    "sell_volume_24h": volume.get("sell_volume_24h", 0.0),
                    "source": "blockmachine",
                }
                subnets.append(subnet)
                time.sleep(BATCH_DELAY)
            except Exception as exc:
                logger.debug("Error fetching data for netuid %d: %s", netuid, exc)
                subnets.append({"netuid": netuid, "name": f"SN{netuid}", "price": 0,
                                "source": "blockmachine", "degraded": True})
        logger.info("get_all_subnet_data: fetched %d subnets from Blockmachine", len(subnets))
        return subnets

_default_client = None

def get_default_client():
    global _default_client
    if _default_client is None:
        _default_client = ChainClient()
    return _default_client
