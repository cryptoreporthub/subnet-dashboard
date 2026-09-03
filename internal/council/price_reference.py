"""Horizon-end price lookup from price_cache candles (Phase J1)."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

PRICE_CACHE_PATH = os.path.join("data", "price_cache.json")
PREDICTIONS_PATH = os.path.join("data", "predictions.json")
# Hourly OHLCV is the canonical resolver source. A single quality-checked
# candle within this window is preferable to retiring valid calls because the
# feed cannot provide three 15-minute candles.
CANDLE_LOOKUP_MINUTES = 90
MIN_CANDLES_FOR_GRADE = 1


def _load_cache(path: Optional[str] = None) -> Dict[str, Any]:
    resolved = path or PRICE_CACHE_PATH
    try:
        with open(resolved, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _parse_ts(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    try:
        text = str(raw).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _candles_for_netuid(cache: Dict[str, Any], netuid: Any) -> List[Dict[str, Any]]:
    key = str(netuid)
    block = cache.get(key)
    if not isinstance(block, dict):
        # Defensive fallback: try the raw value in case it was stored as a
        # non-string key (e.g. integer).  This should not happen once all
        # writers normalise at write time, but we log so mis-attributions are
        # visible rather than silent.
        block = cache.get(netuid)
        if isinstance(block, dict):
            logger.warning(
                "price_cache key inconsistency: netuid %r stored under non-string key %r "
                "instead of canonical string key %r — writer is not normalising at write time",
                netuid,
                netuid,
                key,
            )
    if not isinstance(block, dict):
        logger.warning(
            "price_cache missing key for netuid %r (tried %r and %r) — "
            "subnet will be un-gradeable until the cache is refreshed",
            netuid,
            key,
            netuid,
        )
        return []
    candles = block.get("candles") or []
    result = [c for c in candles if isinstance(c, dict)]
    if not result:
        logger.warning(
            "price_cache block for netuid %r (key %r) contains no valid candles — "
            "subnet will be un-gradeable until the cache is refreshed",
            netuid,
            key,
        )
    return result


def normalize_price_cache_keys(cache_path: str = PRICE_CACHE_PATH) -> int:
    """Rewrite *cache_path* so every top-level key is a canonical string.

    Canonical form: plain integer netuids are stored as their string
    representation (e.g. ``"1"``, not ``1`` or ``"01"``).  Keys that are
    already in canonical form are left untouched.

    Returns the number of keys that were renamed.  Raises no exception on I/O
    failure (logs a warning instead) so callers can treat this as best-effort.

    Writers (``fetch_ohlcv``) already use ``str(subnet_id)`` as the cache key,
    so in practice this function is a safety net for existing files written by
    older code or external tools.
    """
    try:
        with open(cache_path, "r", encoding="utf-8") as fh:
            disk: Dict[str, Any] = json.load(fh)
        if not isinstance(disk, dict):
            return 0
    except Exception as exc:
        logger.warning("normalize_price_cache_keys: could not read %s: %s", cache_path, exc)
        return 0

    renamed = 0
    normalised: Dict[str, Any] = {}
    for raw_key, block in disk.items():
        # Attempt to derive the canonical string key.
        try:
            canonical = str(int(raw_key))
        except (ValueError, TypeError):
            # Non-integer key (e.g. "107.alpha") — keep as-is.
            canonical = raw_key

        if canonical != raw_key:
            logger.warning(
                "normalize_price_cache_keys: renaming cache key %r → %r in %s",
                raw_key,
                canonical,
                cache_path,
            )
            renamed += 1

        # In case of a collision (both "01" and "1" exist), the later iteration
        # wins; log so the operator is aware.
        if canonical in normalised:
            logger.warning(
                "normalize_price_cache_keys: key collision for canonical key %r "
                "(raw keys %r and existing entry) — keeping last-seen value",
                canonical,
                raw_key,
            )
        normalised[canonical] = block

    if renamed:
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(cache_path) or ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(normalised, fh)
            os.replace(tmp, cache_path)
        except Exception as exc:
            logger.warning("normalize_price_cache_keys: could not write %s: %s", cache_path, exc)
            if os.path.exists(tmp):
                os.unlink(tmp)

    return renamed


def audit_cache_coverage(
    predictions_path: str,
    cache_path: str = PRICE_CACHE_PATH,
) -> Dict[str, Any]:
    """Check that every netuid in *predictions_path* has non-empty candles in *cache_path*.

    Returns a dict::

        {
            "ok": [netuids whose candle block is non-empty],
            "missing": [netuids absent from the cache],
            "empty": [netuids present but with zero valid candles],
        }

    Logs a warning for every netuid in ``missing`` or ``empty``.
    """
    try:
        with open(predictions_path, "r", encoding="utf-8") as fh:
            pdata = json.load(fh)
    except Exception:
        return {"ok": [], "missing": [], "empty": []}

    cache = _load_cache(cache_path)

    all_preds = list(pdata.get("predictions") or []) + list(pdata.get("resolved") or [])
    seen: set = set()
    for p in all_preds:
        uid = p.get("netuid")
        if uid is not None:
            seen.add(str(uid))

    ok: List[str] = []
    missing: List[str] = []
    empty: List[str] = []

    for uid_str in sorted(seen, key=lambda x: int(x) if x.isdigit() else 0):
        block = cache.get(uid_str)
        if not isinstance(block, dict):
            missing.append(uid_str)
            logger.warning(
                "audit_cache_coverage: netuid %s has no entry in price_cache — it is un-gradeable",
                uid_str,
            )
            continue
        candles = [c for c in (block.get("candles") or []) if isinstance(c, dict)]
        if not candles:
            empty.append(uid_str)
            logger.warning(
                "audit_cache_coverage: netuid %s has a cache entry but zero valid candles — "
                "it is un-gradeable",
                uid_str,
            )
        else:
            ok.append(uid_str)

    return {"ok": ok, "missing": missing, "empty": empty}


def cache_coverage_strict_enabled() -> bool:
    """When true (CI/staging), incomplete coverage aborts worker startup."""
    return os.environ.get("CACHE_COVERAGE_STRICT", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def run_startup_cache_coverage_audit(
    *,
    predictions_path: str = PREDICTIONS_PATH,
    cache_path: str = PRICE_CACHE_PATH,
) -> Dict[str, Any]:
    """Startup gate: every prediction netuid should have gradeable candles in price_cache.

    Normal mode logs warnings and continues. Set ``CACHE_COVERAGE_STRICT=true`` to
  abort when any netuid is missing or has an empty candle block.
    """
    if not os.path.exists(predictions_path):
        logger.info("startup cache coverage audit skipped (no %s)", predictions_path)
        return {"ok": [], "missing": [], "empty": [], "skipped": True}

    renamed = normalize_price_cache_keys(cache_path)
    if renamed:
        logger.info(
            "startup cache coverage: normalized %s non-canonical price_cache key(s)",
            renamed,
        )

    report = audit_cache_coverage(predictions_path, cache_path)
    report["skipped"] = False
    missing = list(report.get("missing") or [])
    empty = list(report.get("empty") or [])
    ok = list(report.get("ok") or [])
    gaps = len(missing) + len(empty)

    if gaps:
        logger.warning(
            "startup cache coverage audit: %s ok, %s missing cache keys, %s empty "
            "candle blocks — resolver may retire as missing_price_at_horizon",
            len(ok),
            len(missing),
            len(empty),
        )
        if cache_coverage_strict_enabled():
            raise RuntimeError(
                "CACHE_COVERAGE_STRICT: "
                f"{gaps} prediction netuid(s) lack gradeable candles "
                f"(missing={missing}, empty={empty})"
            )
    else:
        logger.info(
            "startup cache coverage audit: %s prediction netuid(s) covered in price_cache",
            len(ok),
        )
    return report


def _window_candles(
    candles: List[Dict[str, Any]],
    resolve_at: datetime,
    window_minutes: int = CANDLE_LOOKUP_MINUTES,
) -> List[Dict[str, Any]]:
    delta_sec = window_minutes * 60
    out: List[Dict[str, Any]] = []
    target = resolve_at.timestamp()
    for candle in candles:
        ts = _parse_ts(candle.get("timestamp"))
        if ts is None:
            continue
        if abs(ts.timestamp() - target) <= delta_sec:
            out.append(candle)
    return out


def _median_price(candles: List[Dict[str, Any]]) -> float:
    closes = []
    for c in candles:
        try:
            close = float(c.get("close", 0) or 0)
            if close > 0:
                closes.append(close)
        except (TypeError, ValueError):
            continue
    if not closes:
        return 0.0
    closes.sort()
    mid = len(closes) // 2
    if len(closes) % 2:
        return closes[mid]
    return (closes[mid - 1] + closes[mid]) / 2


def _vwap_price(candles: List[Dict[str, Any]]) -> float:
    num = 0.0
    den = 0.0
    for c in candles:
        try:
            close = float(c.get("close", 0) or 0)
            vol = float(c.get("volume", 0) or 0)
        except (TypeError, ValueError):
            continue
        if close <= 0:
            continue
        weight = vol if vol > 0 else 1.0
        num += close * weight
        den += weight
    if den <= 0:
        return _median_price(candles)
    return num / den


def price_at_resolve_at(
    netuid: Any,
    resolve_at: datetime,
    *,
    cache: Optional[Dict[str, Any]] = None,
    cache_path: str = PRICE_CACHE_PATH,
) -> Tuple[str, float, Dict[str, Any]]:
    """Return (status, price, meta). status: ok | ungradeable. Hydrates cold cache on miss (#888)."""
    cache = cache if cache is not None else _load_cache(cache_path)
    status, price, meta = _resolve_at_inner(netuid, resolve_at, cache)

    if status == "ok" and price > 0:
        return status, price, meta

    if _hydrate_on_miss_enabled() and _hydrate_once(netuid, cache_path):
        refreshed = _load_cache(cache_path)
        status, price, meta = _resolve_at_inner(netuid, resolve_at, refreshed)
        if status == "ok" and price > 0:
            return status, price, meta

    return "ungradeable", 0.0, meta


def _resolve_at_inner(
    netuid: Any,
    resolve_at: datetime,
    cache: Dict[str, Any],
) -> Tuple[str, float, Dict[str, Any]]:
    """Original lookup body (unchanged). status: ok | ungradeable."""
    candles = _candles_for_netuid(cache, netuid)
    window = _window_candles(candles, resolve_at)
    meta: Dict[str, Any] = {
        "price_source": None,
        "price_lag_seconds": None,
        "candles_in_window": len(window),
    }

    if len(window) < MIN_CANDLES_FOR_GRADE:
        return "ungradeable", 0.0, meta

    total_volume = sum(float(c.get("volume", 0) or 0) for c in window)
    if total_volume <= 0:
        # ponytail: thin subnets often lack candle volume — median close still grades price
        price = _median_price(window)
        if price <= 0:
            return "ungradeable", 0.0, meta
        meta["price_source"] = "median_no_volume"
        nearest = min(
            (c for c in window if _parse_ts(c.get("timestamp"))),
            key=lambda c: abs(_parse_ts(c.get("timestamp")).timestamp() - resolve_at.timestamp()),  # type: ignore
            default=None,
        )
        if nearest:
            ts = _parse_ts(nearest.get("timestamp"))
            if ts:
                meta["price_lag_seconds"] = int(abs(ts.timestamp() - resolve_at.timestamp()))
        return "ok", float(price), meta

    price = _vwap_price(window)
    if price <= 0:
        price = _median_price(window)
        meta["price_source"] = "median"
    else:
        meta["price_source"] = "vwap"

    nearest = min(
        (c for c in window if _parse_ts(c.get("timestamp"))),
        key=lambda c: abs(_parse_ts(c.get("timestamp")).timestamp() - resolve_at.timestamp()),  # type: ignore
        default=None,
    )
    if nearest:
        ts = _parse_ts(nearest.get("timestamp"))
        if ts:
            meta["price_lag_seconds"] = int(abs(ts.timestamp() - resolve_at.timestamp()))

    return "ok", float(price), meta


# ----------------------------------------------------------------
# Hydrate-on-miss (issue #888): when grading finds no candle window at
# resolve_at, force a fresh OHLCV fetch for that netuid (once per interval)
# and retry before retiring the prediction as ungradeable/expired.
# Env-gated so production behavior is unchanged until explicitly enabled in
# fly.toml (CALIBRATION_HYDRATE_ON_MISS=true).
# ----------------------------------------------------------------
_hydrate_memo: Dict[str, float] = {}
_hydrate_hist_memo: Dict[str, float] = {}
_hydrate_min_interval = int(os.environ.get("CALIBRATION_HYDRATE_MIN_INTERVAL", "900"))
_resolver_hydration_budget: ContextVar[Optional[int]] = ContextVar(
    "resolver_hydration_budget", default=None
)
_hydration_recorder: ContextVar[Optional[Callable[[float], None]]] = ContextVar(
    "resolver_hydration_recorder", default=None
)


@contextmanager
def hydration_timing(recorder: Optional[Callable[[float], None]]):
    """Record bounded hydration durations for the active resolver cycle."""
    token = _hydration_recorder.set(recorder)
    try:
        yield
    finally:
        _hydration_recorder.reset(token)


def _record_hydration_duration(duration_ms: float) -> None:
    recorder = _hydration_recorder.get()
    if recorder is not None:
        recorder(duration_ms)


def _timed_hydration(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        started = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            _record_hydration_duration((time.perf_counter() - started) * 1000)

    return wrapper


@contextmanager
def resolver_hydration_budget(max_attempts: int):
    """Bound cache-miss fetches for one resolver cycle without changing callers."""
    token = _resolver_hydration_budget.set(max(0, int(max_attempts)))
    try:
        yield
    finally:
        _resolver_hydration_budget.reset(token)

# Predictions whose resolve_at is older than this many hours need more than the
# default 7-day lookback to reach the horizon candle.
_HIST_HYDRATION_THRESHOLD_HOURS = 24.0

# Hard cap on how many days of OHLCV history we will request for a single
# historical hydration attempt.  Predictions older than this limit are retired
# with a distinct reason rather than triggering an unboundedly large API fetch
# that could time out or block the regrade loop.
# Configurable via CALIBRATION_HIST_MAX_DAYS env var; default 30 days.
CALIBRATION_HIST_MAX_DAYS = int(os.environ.get("CALIBRATION_HIST_MAX_DAYS", "30"))


def _hydrate_on_miss_enabled() -> bool:
    return os.environ.get("CALIBRATION_HYDRATE_ON_MISS", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _consume_resolver_hydration_budget() -> bool:
    remaining = _resolver_hydration_budget.get()
    if remaining is None:
        return True
    if remaining <= 0:
        return False
    _resolver_hydration_budget.set(remaining - 1)
    return True


def _bust_cache_ttl(netuid: Any, cache_path: str) -> None:
    """Set cached_at=0 for a netuid block so the next fetch_ohlcv bypasses the TTL.

    Mirrors pump_lead_recover.hydrate_candles_for_resolve: fetch_ohlcv with
    use_cache=True would serve the stale-but-window-missing entry straight back
    within CACHE_TTL, making the hydration a silent no-op.
    """
    import tempfile

    key = str(netuid)
    disk: Dict[str, Any] = {}
    try:
        with open(cache_path, "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            disk = loaded
    except Exception:
        pass
    block = disk.get(key)
    if not isinstance(block, dict):
        return
    block = dict(block)
    block["cached_at"] = 0.0
    disk[key] = block
    os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(cache_path) or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(disk, fh)
        os.replace(tmp_path, cache_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def hydrate_candles_for_netuid(netuid: Any, cache_path: str = PRICE_CACHE_PATH) -> bool:
    """Public: force a fresh OHLCV fetch for *netuid* (rate-limited per interval).

    Returns True if a fetch was dispatched, False if the rate-limit is still
    active or if the fetch raised an exception.  Callers should reload the
    cache and retry their candle lookup after a True return.
    """
    return _hydrate_once(netuid, cache_path)


@_timed_hydration
def hydrate_candles_for_netuid_historical(
    netuid: Any,
    resolve_at: datetime,
    cache_path: str = PRICE_CACHE_PATH,
) -> Optional[bool]:
    """Fetch a historical OHLCV window large enough to cover *resolve_at*.

    ``hydrate_candles_for_netuid`` fetches only the current rolling window
    (DEFAULT_DAYS ≈ 7 days).  When *resolve_at* is more than ~24 h in the
    past, that window will not contain the target candle.  This function
    computes the number of days needed to reach *resolve_at* and calls
    ``fetch_ohlcv`` with that extended lookback.

    Rate-limited separately from the standard hydration (once per interval per
    netuid) so callers do not need to coordinate the two paths.

    Returns:
        ``True``  — a fetch was dispatched successfully.
        ``False`` — rate-limited or fetch raised an exception.
        ``None``  — *resolve_at* is older than ``CALIBRATION_HIST_MAX_DAYS``
                    (default 30).  The caller should retire the prediction with
                    ``retirement_reason="horizon_too_old_for_history"`` instead
                    of issuing an unboundedly large API request.
    """
    import math

    key = str(netuid)
    now_ts = time.time()

    # Check age before the rate-limit memo so that "too old" is detected even
    # when the memo would otherwise block a fetch.
    now_dt = datetime.now(timezone.utc)
    age_hours = (now_dt - resolve_at).total_seconds() / 3600.0
    # Add 2-day buffer so the derived candle series covers the target window
    # even when the upstream TAO/USD history starts exactly at the cutoff.
    days_needed = max(7, math.ceil(age_hours / 24.0) + 2)

    if days_needed > CALIBRATION_HIST_MAX_DAYS:
        logger.warning(
            "hydrate_candles_for_netuid_historical: netuid %s resolve_at %s requires %d days "
            "of history which exceeds the cap of %d (CALIBRATION_HIST_MAX_DAYS); "
            "prediction will be retired as horizon_too_old_for_history",
            netuid,
            resolve_at.isoformat(),
            days_needed,
            CALIBRATION_HIST_MAX_DAYS,
        )
        return None

    if now_ts - _hydrate_hist_memo.get(key, 0.0) < _hydrate_min_interval:
        return False
    if not _consume_resolver_hydration_budget():
        return False
    _hydrate_hist_memo[key] = now_ts
    try:
        _bust_cache_ttl(netuid, cache_path)

        from internal.indicators.price_fetcher import fetch_ohlcv
        fetch_ohlcv(
            str(netuid),
            days=days_needed,
            use_cache=True,
            allow_synthetic=False,
            cache_path=cache_path,
        )
        return True
    except Exception:
        return False


@_timed_hydration
def _hydrate_once(netuid: Any, cache_path: str) -> bool:
    """Force a fresh OHLCV fetch for a netuid at most once per interval."""
    key = str(netuid)
    now = time.time()
    if now - _hydrate_memo.get(key, 0.0) < _hydrate_min_interval:
        return False
    if not _consume_resolver_hydration_budget():
        return False
    _hydrate_memo[key] = now
    try:
        _bust_cache_ttl(netuid, cache_path)

        from internal.indicators.price_fetcher import fetch_ohlcv
        fetch_ohlcv(
            str(netuid),
            use_cache=True,
            allow_synthetic=False,
            cache_path=cache_path,
        )
        return True
    except Exception:
        return False
