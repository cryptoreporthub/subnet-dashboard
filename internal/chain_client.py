"""Lightweight HTTPS JSON-RPC client for Bittensor-compatible nodes.

Designed for Blockmachine's free public RPC (https://rpc.blockmachine.io)
but works with any Substrate/Bittensor JSON-RPC endpoint that exposes the
Bittensor runtime calls and state storage.

Primary data source for the dashboard's layered pipeline:
  Layer 1 (Primary):   Blockmachine RPC — real-time, free, no API key
  Layer 2 (Supp):      TaoStats API — derived metrics, 5 calls/min
  Layer 3 (Fallback):  TaoMarketCap — display metadata only
"""

import binascii
import logging
import os
import sqlite3
import struct
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

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


def _init_volume_db():
    os.makedirs(os.path.dirname(VOLUME_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(VOLUME_DB_PATH)
    c = conn.cursor()
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
    c.execute("""
        CREATE TABLE IF NOT EXISTS volume_24h (
            netuid INTEGER PRIMARY KEY,
            buys_24h INTEGER DEFAULT 0,
            sells_24h INTEGER DEFAULT 0,
            buy_volume_24h REAL DEFAULT 0.0,
            sell_volume_24h REAL DEFAULT 0.0,
            last_updated TEXT
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


def _contains_swap_event(raw, netuid):
    target = struct.pack("<H", netuid)
    return target in raw


class ChainClient:
    def __init__(self, endpoint=DEFAULT_RPC_URL, timeout=DEFAULT_TIMEOUT,
                 retries=DEFAULT_RETRIES, backoff=None):
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff or DEFAULT_BACKOFF
        self._last_health_check = 0.0
        self._healthy = True
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
                response = requests.post(
                    self.endpoint,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data = response.json()
                if "error" in data:
                    raise RuntimeError(data["error"])
                return data.get("result")
            except Exception as exc:
                last_error = exc
                sleep_for = self.backoff[min(attempt, len(self.backoff) - 1)]
                logger.debug("RPC %s attempt %d failed: %s", method, attempt, exc)
                if attempt < self.retries:
                    time.sleep(sleep_for)
        raise last_error or RuntimeError(f"RPC call to {method} failed")

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

    def get_alpha_price(self, netuid):
        try:
            result = self._call("swap_currentAlphaPrice", [netuid])
            if result is not None:
                return float(result) / PRICE_SCALE
        except Exception as exc:
            logger.debug("swap_currentAlphaPrice failed for netuid %s: %s", netuid, exc)
        return None

    def get_all_netuids(self):
        if not self.is_healthy():
            return []
        # Method 1: runtime call for total subnets
        try:
            result = self._call_quiet("subnet_getN", [])
            if result is not None:
                total = int(result)
                netuids = list(range(min(total, MAX_NETUIDS)))
                logger.info("get_all_netuids: %d via subnet_getN", len(netuids))
                return netuids
        except Exception:
            pass
        # Method 2: state_call
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
        # Method 3: probe
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
            result = self._call_quiet("state_call", ["Swap_get_pool", _encode_netuid_arg(netuid)])
            if result and result != "0x":
                raw = _hex_to_bytes(result)
                if len(raw) >= 33:
                    offset = 1 if raw[0] in (0, 1) else 0
                    tao_reserve = _decode_scale_u128(raw[offset:offset+16])
                    alpha_reserve = _decode_scale_u128(raw[offset+16:offset+32])
                    tao = tao_reserve / 1e9
                    alpha = alpha_reserve / 1e9
                    root_prop = alpha / (tao + alpha) if (tao + alpha) > 0 else 0
                    return {
                        "netuid": netuid, "liquidity": round(tao + alpha, 4),
                        "total_tao": round(tao, 4), "total_alpha": round(alpha, 4),
                        "root_prop": round(root_prop, 4),
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

    def get_swap_events(self, netuid, block_count=256):
        if not self.is_healthy():
            return {"buys": 0, "sells": 0, "buy_volume_tao": 0.0, "sell_volume_tao": 0.0,
                    "window_blocks": 0, "buys_24h": 0, "sells_24h": 0}
        current_block = self.get_current_block()
        if not current_block:
            return {"buys": 0, "sells": 0, "buy_volume_tao": 0.0, "sell_volume_tao": 0.0,
                    "window_blocks": 0, "buys_24h": 0, "sells_24h": 0}
        start_block = max(0, current_block - block_count)
        buys, sells, buy_vol, sell_vol = 0, 0, 0.0, 0.0
        batch_size = 10
        blocks_scanned = 0
        for batch_start in range(start_block, current_block, batch_size):
            batch_end = min(batch_start + batch_size, current_block)
            for block_num in range(batch_start, batch_end):
                try:
                    block_hash = self._call_quiet("chain_getBlockHash", [block_num])
                    if not block_hash:
                        continue
                    events_result = self._call_quiet("state_getStorage", [
                        "0x26aa394eea5630e07c48ae0c9558cea3a0c8a6e5e1c0e3b0e3b0e3b0e3b0e3b0e3b0e3b0e3b0e3b0e3b0e3b0e3b0e3b0e3b0e3b0",
                    ])
                    if events_result and events_result != "0x":
                        raw = _hex_to_bytes(events_result)
                        if _contains_swap_event(raw, netuid):
                            buys += 1
                    blocks_scanned += 1
                    time.sleep(BATCH_DELAY)
                except Exception:
                    continue
            time.sleep(0.5)
        self._store_volume_snapshot(netuid, buys, sells, buy_vol, sell_vol)
        cumulative = self._get_cumulative_volume_24h(netuid)
        return {
            "buys": buys, "sells": sells, "buy_volume_tao": buy_vol,
            "sell_volume_tao": sell_vol, "window_blocks": blocks_scanned,
            "buys_24h": cumulative.get("buys_24h", 0),
            "sells_24h": cumulative.get("sells_24h", 0),
            "buy_volume_24h": cumulative.get("buy_volume_24h", 0.0),
            "sell_volume_24h": cumulative.get("sell_volume_24h", 0.0),
        }

    def _store_volume_snapshot(self, netuid, buys, sells, buy_vol, sell_vol):
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        conn = sqlite3.connect(VOLUME_DB_PATH)
        c = conn.cursor()
        c.execute("""INSERT OR REPLACE INTO swap_volume
            (netuid, timestamp, buys, sells, buy_volume_tao, sell_volume_tao)
            VALUES (?, ?, ?, ?, ?, ?)""", (netuid, now, buys, sells, buy_vol, sell_vol))
        conn.commit()
        conn.close()

    def _get_cumulative_volume_24h(self, netuid):
        cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 86400))
        conn = sqlite3.connect(VOLUME_DB_PATH)
        c = conn.cursor()
        c.execute("""SELECT COALESCE(SUM(buys), 0), COALESCE(SUM(sells), 0),
            COALESCE(SUM(buy_volume_tao), 0), COALESCE(SUM(sell_volume_tao), 0)
            FROM swap_volume WHERE netuid = ? AND timestamp >= ?""", (netuid, cutoff))
        row = c.fetchone()
        conn.close()
        if row:
            return {"buys_24h": row[0], "sells_24h": row[1],
                    "buy_volume_24h": row[2], "sell_volume_24h": row[3]}
        return {"buys_24h": 0, "sells_24h": 0, "buy_volume_24h": 0.0, "sell_volume_24h": 0.0}

    def get_all_subnet_data(self):
        if not self.is_healthy():
            return []
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
                subnet = {
                    "netuid": netuid, "name": f"SN{netuid}", "price": price or 0.0,
                    "stake": stake.get("stake", 0) if stake else 0,
                    "total_stake": stake.get("total_stake", 0) if stake else 0,
                    "emission": emission or 0.0,
                    "liquidity": pool.get("liquidity", 0) if pool else 0,
                    "total_tao": pool.get("total_tao", 0) if pool else 0,
                    "total_alpha": pool.get("total_alpha", 0) if pool else 0,
                    "root_prop": pool.get("root_prop", 0) if pool else 0,
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
