"""Recover expired/ungradeable predictions that can now be graded.

When predictions resolve while the price cache has no candle window (feed
outage, cold cache), resolver retires them as "expired"/"ungradeable" even
though the price may be recoverable later. With CALIBRATION_HYDRATE_ON_MISS
enabled, price_at_resolve_at now hydrates cold caches, so a recovery sweep can
re-run grading for rows that retired for data reasons — turning expired rows
back into graded outcomes instead of silently inflating expired_rate (this
was 90.5% on 2026-08-11, blocking the trust gate).

Runs inside the outcome snapshot scheduler tick (idempotent, small N; guarded
by hydrate memo so repeated sweeps are cheap).
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import threading
import time
import uuid
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)

_RETIRED = frozenset({"expired", "ungradeable"})
_MAX_RECOVER = 20

# Per-effect receipts for expired-recovery learning. This is not the pump-desk
# learning: {key, kind, state, owner, done} schema in internal/council/learning_effects.py.
LEARNING_EFFECT_RECEIPTS_PATH = os.environ.get(
    "LEARNING_EFFECT_RECEIPTS_PATH",
    os.path.join("data", "learning_effect_receipts.json"),
)

_NORMAL_EFFECTS = ("expert", "impact", "finalize", "scenario", "signal")
_SKIP_EFFECTS = ("finalize", "pump")

_RECEIPTS_MUTEX = threading.RLock()
RECEIPTS_LOCK_TIMEOUT_SECONDS = 5.0
APPLY_LOCK_TIMEOUT_SECONDS = 5.0
_APPLY_MUTEX = threading.Lock()


class LearningEffectApplyLockTimeout(Exception):
    """Raised when the learning-effect apply lock deadline passes."""


def _apply_lock_path() -> str:
    return _receipts_path() + ".apply"


@contextmanager
def _apply_lock() -> Iterator[None]:
    # One deadline for mutex + flock. Path follows the isolated receipts journal.
    deadline = time.monotonic() + APPLY_LOCK_TIMEOUT_SECONDS
    acquired = _APPLY_MUTEX.acquire(timeout=max(0.0, deadline - time.monotonic()))
    try:
        if not acquired:
            raise LearningEffectApplyLockTimeout("timed out waiting for apply mutex")
        path = _apply_lock_path()
        parent = os.path.dirname(path) or "data"
        os.makedirs(parent, exist_ok=True)
        with open(path, "a+", encoding="utf-8") as lock:
            while time.monotonic() < deadline:
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(0.05)
            else:
                raise LearningEffectApplyLockTimeout("timed out waiting for apply flock")
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    finally:
        if acquired:
            _APPLY_MUTEX.release()


def _ledger_effect_state(key, effect) -> str:
    """Re-read durable effect state for one row/effect under the apply lock."""
    from internal.learning.predictions_store import load_predictions, _row_key

    data = load_predictions(fail_closed=True)
    for bucket in ("predictions", "resolved"):
        for row in data.get(bucket) or []:
            if not isinstance(row, dict):
                continue
            if _row_key(row) != key:
                continue
            effects = row.get("learning_effects") if isinstance(row.get("learning_effects"), dict) else {}
            if effect in (effects.get("indeterminate") or []):
                return "indeterminate"
            if effect in (effects.get("done") or []):
                return "done"
            if effect in (effects.get("pending") or []):
                return "pending"
            return "absent"
    return "absent"


class LearningEffectReceiptsUnreadable(Exception):
    """Raised when the effect-receipt journal exists but cannot be read."""


class LearningEffectReceiptsLockTimeout(Exception):
    """Raised when the receipt journal lock cannot be acquired in time."""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _prediction_still_open(
    pred_id: object,
    *,
    observation: Optional[dict] = None,
    netuid: object = None,
    row: Optional[dict] = None,
) -> bool:
    """True when a matching open position remains, or the book is unreadable."""
    if row:
        if pred_id is None:
            pred_id = row.get("id")
        if netuid is None:
            netuid = row.get("netuid")
    try:
        from internal.judges.portfolios import observe_portfolios, _position_matches

        obs = observation if observation is not None else observe_portfolios()
        kind = obs.get("kind")
        if kind == "missing":
            return False
        if kind != "readable":
            return True
        from internal.judges.portfolios import _idless_ambiguous

        data = obs.get("data") or {}
        for name in ("oracle", "echo", "pulse"):
            judge = data.get(name) or {}
            for pos in judge.get("open_positions") or []:
                if _position_matches(pos, pred_id, netuid, row=row):
                    return True
                if _idless_ambiguous(pos, pred_id, netuid, row=row):
                    return True
    except Exception:
        return True
    return False


def _receipts_path() -> str:
    return os.environ.get("LEARNING_EFFECT_RECEIPTS_PATH") or LEARNING_EFFECT_RECEIPTS_PATH


@contextmanager
def _receipts_lock(*, exclusive: bool = True) -> Iterator[None]:
    # _RECEIPTS_MUTEX still serializes in-process readers; LOCK_SH is for
    # cross-process overlap only.
    acquired = _RECEIPTS_MUTEX.acquire(timeout=RECEIPTS_LOCK_TIMEOUT_SECONDS)
    try:
        if not acquired:
            raise LearningEffectReceiptsLockTimeout("timed out waiting for receipts mutex")
        path = _receipts_path()
        parent = os.path.dirname(path) or "data"
        # A shared read may makedirs and create the .lock sibling so flock has a
        # path; this is an intentional tradeoff, not a silent write of receipt data.
        os.makedirs(parent, exist_ok=True)
        # Fresh flock budget, independent of how long the mutex wait already took.
        deadline = time.monotonic() + RECEIPTS_LOCK_TIMEOUT_SECONDS
        flag = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        with open(path + ".lock", "a+", encoding="utf-8") as lock:
            while time.monotonic() < deadline:
                try:
                    fcntl.flock(lock.fileno(), flag | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(0.05)
            else:
                raise LearningEffectReceiptsLockTimeout("timed out waiting for receipts flock")
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    finally:
        if acquired:
            _RECEIPTS_MUTEX.release()


def _load_receipts() -> Dict[str, Any]:
    path = _receipts_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        raise LearningEffectReceiptsUnreadable(f"{type(exc).__name__}: {exc}") from exc
    if not isinstance(data, dict):
        raise LearningEffectReceiptsUnreadable("receipts root must be an object")
    return data


def _receipt_token(row_key: Optional[Tuple[Any, ...]], effect: str) -> str:
    return json.dumps([list(row_key) if row_key is not None else None, effect], separators=(",", ":"))


def has_effect_receipt(row_key: Optional[Tuple[Any, ...]], effect: str) -> bool:
    with _receipts_lock(exclusive=False):
        return _receipt_token(row_key, effect) in _load_receipts()


def write_effect_receipt(row_key: Optional[Tuple[Any, ...]], effect: str) -> None:
    path = _receipts_path()
    with _receipts_lock(exclusive=True):
        data = _load_receipts()
        data[_receipt_token(row_key, effect)] = _utcnow_iso()
        parent = os.path.dirname(path) or "data"
        os.makedirs(parent, exist_ok=True)
        tmp = f"{path}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass


def _pending_list(row: Dict[str, Any]) -> List[str]:
    from internal.council import resolver

    if resolver._skip_council_learning(row):
        return list(_SKIP_EFFECTS)
    return list(_NORMAL_EFFECTS)


def _stamp_learning_effects_pending(row: Dict[str, Any]) -> None:
    existing = row.get("learning_effects")
    if isinstance(existing, dict) and existing.get("pending"):
        return
    done = list((existing or {}).get("done") or []) if isinstance(existing, dict) else []
    # New grade cycle: do not carry a prior outcome's indeterminate list.
    row["learning_effects"] = {"pending": _pending_list(row), "done": done, "indeterminate": []}


def _move_effect_on_ledger(row: Dict[str, Any], effect: str) -> None:
    from internal.learning.predictions_store import load_predictions, merge_ledger_changes, _row_key

    key = _row_key(row)
    before = load_predictions(fail_closed=True)
    after = deepcopy(before)
    target = None
    for bucket in ("predictions", "resolved"):
        for candidate in after.get(bucket) or []:
            if not isinstance(candidate, dict):
                continue
            if _row_key(candidate) == key:
                target = candidate
                break
        if target is not None:
            break
    if target is None:
        return
    effects = target.setdefault("learning_effects", {"pending": [], "done": [], "indeterminate": []})
    pending = [name for name in (effects.get("pending") or []) if name != effect]
    done = list(effects.get("done") or [])
    if effect not in done:
        done.append(effect)
    indeterminate = [name for name in (effects.get("indeterminate") or []) if name != effect]
    effects["pending"] = pending
    effects["done"] = done
    effects["indeterminate"] = indeterminate
    from internal.learning.predictions_store import PersistOutcome

    result = merge_ledger_changes(before, after, caller="expired_recovery", trigger="learning_effect_receipt")
    if result.outcome is not PersistOutcome.APPLIED:
        reason = result.reason.value if result.reason is not None else str(result.outcome)
        raise RuntimeError(f"learning effect ledger stamp not applied: {reason}")
    committed = set(result.committed_keys or ())
    if committed and key not in committed:
        raise RuntimeError("learning effect ledger stamp did not include the row key")
    row["learning_effects"] = {
        "pending": list(pending),
        "done": list(done),
        "indeterminate": list(indeterminate),
    }


def _mark_effect_indeterminate(row: Dict[str, Any], effect: str) -> None:
    from internal.learning.predictions_store import load_predictions, merge_ledger_changes, _row_key, PersistOutcome

    key = _row_key(row)
    before = load_predictions(fail_closed=True)
    after = deepcopy(before)
    target = None
    for bucket in ("predictions", "resolved"):
        for candidate in after.get(bucket) or []:
            if not isinstance(candidate, dict):
                continue
            if _row_key(candidate) == key:
                target = candidate
                break
        if target is not None:
            break
    if target is None:
        return
    effects = target.setdefault("learning_effects", {"pending": [], "done": [], "indeterminate": []})
    pending = [name for name in (effects.get("pending") or []) if name != effect]
    indeterminate = list(effects.get("indeterminate") or [])
    if effect not in indeterminate:
        indeterminate.append(effect)
    effects["pending"] = pending
    effects["indeterminate"] = indeterminate
    result = merge_ledger_changes(before, after, caller="expired_recovery", trigger="learning_effect_receipt")
    if result.outcome is not PersistOutcome.APPLIED:
        reason = result.reason.value if result.reason is not None else str(result.outcome)
        raise RuntimeError(f"learning effect indeterminate stamp not applied: {reason}")
    committed = set(result.committed_keys or ())
    if committed and key not in committed:
        raise RuntimeError("learning effect indeterminate stamp did not include the row key")
    row["learning_effects"] = {
        "pending": list(pending),
        "done": list(effects.get("done") or []),
        "indeterminate": list(indeterminate),
    }


def recover_expired_predictions(
    *,
    dry_run: bool = False,
    max_rows: int = _MAX_RECOVER,
) -> Dict[str, Any]:
    """Re-resolve retired rows whose price may now be available. Idempotent."""
    from internal.learning.predictions_store import (
        PersistOutcome,
        PredictionsLedgerUnreadable,
        _row_key,
        load_predictions,
        merge_ledger_changes,
        update_stats,
    )
    from internal.council.price_reference import price_at_resolve_at
    from internal.council import resolver
    from internal.council.grading import compute_actual_pct, grade_prediction, is_price_unit_mismatch
    from internal.judges.portfolios import observe_portfolios

    recovered, skipped = 0, 0
    details: List[Dict[str, Any]] = []
    incomplete: List[Any] = []
    close_incomplete: List[Any] = []
    effect_incomplete: List[Any] = []
    receipts_lock_timed_out: List[Any] = []
    receipts_write_failed: List[Any] = []
    apply_lock_timed_out: List[Any] = []

    def _fail(reason: str, *, error: str = "", recovered: int = 0, **extra: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "ok": False,
            "reason": reason,
            "error": error or reason,
            "dry_run": dry_run,
            "recovered": recovered,
            "skipped": skipped,
            "details": details[:10],
        }
        payload.update(extra)
        return payload

    try:
        data = load_predictions(fail_closed=True)
    except PredictionsLedgerUnreadable as exc:
        return _fail("ledger_unreadable", error=str(exc) or exc.kind)
    except OSError as exc:
        return _fail("ledger_unreadable", error=str(exc))

    observation = observe_portfolios()
    retryable_pending: List[Dict[str, Any]] = []
    retryable_indeterminate: List[Dict[str, Any]] = []
    for row in data.get("resolved") or []:
        if not isinstance(row, dict):
            continue
        effects = row.get("learning_effects") if isinstance(row.get("learning_effects"), dict) else {}
        pending = effects.get("pending") or []
        indeterminate = effects.get("indeterminate") or []
        outcome = str(row.get("outcome") or "").lower()
        if pending and outcome not in _RETIRED:
            retryable_pending.append(row)
        if indeterminate and outcome not in _RETIRED:
            retryable_indeterminate.append(row)

    if not dry_run and observation.get("kind") == "unreadable" and not retryable_pending:
        return _fail(
            "portfolio_unobservable",
            error=str(observation.get("error") or observation.get("kind") or "unobservable"),
        )

    before = deepcopy(data)
    resolved = data.get("resolved", []) or []
    recovered_rows: List[Dict[str, Any]] = []

    for row in resolved:
        if recovered >= max_rows:
            break
        if not isinstance(row, dict):
            continue
        outcome = str(row.get("outcome") or "").lower()
        if outcome not in _RETIRED:
            continue

        resolve_at_raw = row.get("resolve_at") or row.get("resolved_at") or row.get("horizon_end")
        if not resolve_at_raw:
            skipped += 1
            continue
        try:
            resolve_at = datetime.fromisoformat(str(resolve_at_raw).replace("Z", "+00:00"))
            if resolve_at.tzinfo is None:
                resolve_at = resolve_at.replace(tzinfo=timezone.utc)
            resolve_at = resolve_at.astimezone(timezone.utc)
        except Exception:
            skipped += 1
            continue

        netuid = row.get("netuid")
        if netuid is None:
            skipped += 1
            continue

        try:
            status, price, meta = price_at_resolve_at(netuid, resolve_at)
        except Exception:
            skipped += 1
            continue
        if status != "ok" or price <= 0:
            skipped += 1
            continue

        try:
            reference = float(
                row.get("reference_price")
                or (row.get("subnet_snapshot") or {}).get("price")
                or 0
            )
        except (TypeError, ValueError):
            reference = 0.0
        if reference <= 0:
            skipped += 1
            continue
        if is_price_unit_mismatch(reference, price):
            skipped += 1
            continue

        actual_pct = compute_actual_pct(reference, price)
        correct, new_outcome = grade_prediction(row, actual_pct)

        if dry_run:
            details.append({
                "netuid": netuid,
                "id": row.get("id"),
                "would_grade": new_outcome,
                "price": price,
            })
            recovered += 1
            continue

        from internal.council.capture import stamp_capture_fields

        capture = stamp_capture_fields(row, actual_pct)
        expert, _source = resolver._stamp_expert_attribution(row)
        resolver._ensure_subnet_snapshot(row)
        row["actual_pct"] = actual_pct
        row["outcome"] = new_outcome
        row["correct"] = bool(correct)
        row["status"] = "resolved"
        row["resolved_price"] = price
        row["resolved_at"] = resolve_at.isoformat().replace("+00:00", "Z")
        row["recovered_at"] = _utcnow_iso()
        row["recovery"] = {"from": outcome, "price_source": meta.get("price_source")}
        _stamp_learning_effects_pending(row)
        recovered_rows.append({
            "row": row,
            "actual_pct": actual_pct,
            "new_outcome": new_outcome,
            "correct": bool(correct),
            "price": price,
            "resolve_at": resolve_at,
            "meta": meta,
            "capture": capture,
            "expert": expert,
            "prior_outcome": outcome,
        })
        recovered += 1

    def _run_effects(items: List[Dict[str, Any]]) -> None:
        for item in items:
            row = item["row"]
            key = _row_key(row)
            effects_row = row.get("learning_effects")
            if isinstance(effects_row, dict):
                pending = list(effects_row.get("pending") or [])
                indeterminate = list(effects_row.get("indeterminate") or [])
            else:
                pending = _pending_list(row)
                indeterminate = []
            # Dedup: an effect is processed once. Indeterminate names take the
            # receipt-only branch even if they also appear in pending.
            work = pending + [name for name in indeterminate if name not in pending]
            indeterminate_set = set(indeterminate)
            for effect in list(work):
                try:
                    already = has_effect_receipt(key, effect)
                except LearningEffectReceiptsUnreadable:
                    logger.exception("expired recovery receipts unreadable")
                    effect_incomplete.append(row.get("id"))
                    incomplete.append(row.get("id"))
                    continue
                except LearningEffectReceiptsLockTimeout:
                    logger.exception("expired recovery receipts lock timeout")
                    effect_incomplete.append(row.get("id"))
                    incomplete.append(row.get("id"))
                    receipts_lock_timed_out.append(row.get("id"))
                    continue
                if already or effect in indeterminate_set:
                    if not already:
                        try:
                            write_effect_receipt(key, effect)
                        except LearningEffectReceiptsLockTimeout:
                            logger.exception("expired recovery indeterminate receipt rewrite timed out")
                            effect_incomplete.append(row.get("id"))
                            incomplete.append(row.get("id"))
                            receipts_lock_timed_out.append(row.get("id"))
                            continue
                        except Exception:
                            logger.exception("expired recovery indeterminate receipt rewrite failed")
                            effect_incomplete.append(row.get("id"))
                            incomplete.append(row.get("id"))
                            receipts_write_failed.append(row.get("id"))
                            continue
                    try:
                        _move_effect_on_ledger(row, effect)
                    except Exception:
                        logger.exception("expired recovery receipt stamp failed")
                        effect_incomplete.append(row.get("id"))
                        incomplete.append(row.get("id"))
                        raise
                    continue
                try:
                    with _apply_lock():
                        try:
                            if has_effect_receipt(key, effect):
                                state = "receipted"
                            else:
                                state = _ledger_effect_state(key, effect)
                        except LearningEffectReceiptsLockTimeout:
                            logger.exception("expired recovery under-lock recheck lock timeout")
                            effect_incomplete.append(row.get("id"))
                            incomplete.append(row.get("id"))
                            receipts_lock_timed_out.append(row.get("id"))
                            continue
                        except LearningEffectReceiptsUnreadable:
                            # Existing unreadable path surfaces as effects_incomplete.
                            logger.exception("expired recovery under-lock recheck unreadable")
                            effect_incomplete.append(row.get("id"))
                            incomplete.append(row.get("id"))
                            continue
                        except Exception:
                            logger.exception("expired recovery under-lock recheck failed")
                            effect_incomplete.append(row.get("id"))
                            incomplete.append(row.get("id"))
                            continue
                        if state in ("receipted", "indeterminate", "done"):
                            if state == "indeterminate":
                                try:
                                    write_effect_receipt(key, effect)
                                except LearningEffectReceiptsLockTimeout:
                                    effect_incomplete.append(row.get("id"))
                                    incomplete.append(row.get("id"))
                                    receipts_lock_timed_out.append(row.get("id"))
                                    continue
                                except Exception:
                                    effect_incomplete.append(row.get("id"))
                                    incomplete.append(row.get("id"))
                                    receipts_write_failed.append(row.get("id"))
                                    continue
                            try:
                                _move_effect_on_ledger(row, effect)
                            except Exception:
                                effect_incomplete.append(row.get("id"))
                                incomplete.append(row.get("id"))
                                raise
                            continue
                        if effect == "expert":
                            if not resolver._skip_council_learning(row):
                                resolver._nudge_attributed_expert(
                                    row,
                                    correct=item.get("correct"),
                                    capture=item.get("capture"),
                                    stamped_expert=item.get("expert"),
                                )
                        elif effect == "impact":
                            if not resolver._skip_council_learning(row):
                                resolver._nudge_impact_strength(row, item.get("correct"))
                        elif effect == "finalize":
                            from internal.council.capture import stamp_capture_fields as _stamp
                            from internal.judges.portfolios import observe_portfolios

                            capture = item.get("capture") or _stamp(row, float(row.get("actual_pct") or 0))
                            resolve_at = item.get("resolve_at") or row.get("resolved_at")
                            if hasattr(resolve_at, "isoformat"):
                                resolved_at = resolve_at.isoformat().replace("+00:00", "Z")
                            else:
                                resolved_at = str(resolve_at or row.get("resolved_at") or _utcnow_iso())
                            warnings_before = list(row.get("side_effect_warnings") or [])
                            resolver.atomic_finalize_resolution(
                                row,
                                actual_pct=float(item.get("actual_pct") if item.get("actual_pct") is not None else row.get("actual_pct") or 0),
                                outcome=str(item.get("new_outcome") or row.get("outcome") or ""),
                                correct=item.get("correct") if item.get("correct") is not None else row.get("correct"),
                                resolved_price=float(item.get("price") if item.get("price") is not None else row.get("resolved_price") or 0),
                                resolved_at=resolved_at,
                                price_meta=item.get("meta"),
                                apply_judge_nudge=False,
                            )
                            warnings_after = list(row.get("side_effect_warnings") or [])
                            fresh_close_warning = any(
                                name in warnings_after and name not in warnings_before
                                for name in ("on_prediction_resolved", "portfolios_unobservable")
                            )
                            obs = observe_portfolios()
                            still_open = False
                            if obs.get("kind") == "unreadable":
                                still_open = True
                            elif obs.get("kind") != "missing":
                                still_open = _prediction_still_open(row.get("id"), row=row, observation=obs)
                            if still_open or fresh_close_warning:
                                close_incomplete.append(row.get("id"))
                                incomplete.append(row.get("id"))
                                continue
                        elif effect == "scenario":
                            if not resolver._skip_council_learning(row):
                                resolver._record_scenario_outcome(
                                    row,
                                    item.get("actual_pct", row.get("actual_pct")),
                                    item.get("new_outcome", row.get("outcome")),
                                    item.get("correct", row.get("correct")),
                                    item.get("expert", row.get("expert")),
                                )
                        elif effect == "signal":
                            if not resolver._skip_council_learning(row):
                                resolver._nudge_signal_weights(
                                    row, item.get("correct", row.get("correct")), capture=item.get("capture")
                                )
                        elif effect == "pump":
                            from internal.learning.pump_calibration import maybe_adapt_after_resolve

                            maybe_adapt_after_resolve()
                        # Crash window: if we die after the effect applies and before this
                        # receipt or indeterminate marker lands, retry can double-apply.
                        # If the receipt write fails, retry the indeterminate merge once
                        # before giving up. If both mark attempts fail, the effect stays
                        # pending (accepted residual). Do not add a pre-effect claim.
                        try:
                            write_effect_receipt(key, effect)
                        except Exception as write_exc:
                            logger.exception("expired recovery effect applied but receipt write failed")
                            mark_failed = False
                            try:
                                _mark_effect_indeterminate(row, effect)
                            except Exception:
                                logger.exception("expired recovery indeterminate mark failed; retrying once")
                                try:
                                    _mark_effect_indeterminate(row, effect)
                                except Exception:
                                    logger.exception("expired recovery indeterminate mark failed twice")
                                    mark_failed = True
                            if mark_failed:
                                effect_incomplete.append(row.get("id"))
                                incomplete.append(row.get("id"))
                                if isinstance(write_exc, LearningEffectReceiptsLockTimeout):
                                    receipts_lock_timed_out.append(row.get("id"))
                                else:
                                    receipts_write_failed.append(row.get("id"))
                                continue
                            effect_incomplete.append(row.get("id"))
                            incomplete.append(row.get("id"))
                            if isinstance(write_exc, LearningEffectReceiptsLockTimeout):
                                receipts_lock_timed_out.append(row.get("id"))
                            else:
                                receipts_write_failed.append(row.get("id"))
                            continue
                        _move_effect_on_ledger(row, effect)
                except LearningEffectApplyLockTimeout:
                    logger.exception("expired recovery apply lock timeout")
                    effect_incomplete.append(row.get("id"))
                    incomplete.append(row.get("id"))
                    apply_lock_timed_out.append(row.get("id"))
                    continue
                except LearningEffectReceiptsLockTimeout:
                    logger.exception("expired recovery receipts lock timeout")
                    effect_incomplete.append(row.get("id"))
                    incomplete.append(row.get("id"))
                    receipts_lock_timed_out.append(row.get("id"))
                    continue
                except Exception:
                    logger.exception("expired recovery post-commit effects failed")
                    effect_incomplete.append(row.get("id"))
                    incomplete.append(row.get("id"))
                    raise

    if not dry_run and recovered:
        try:
            update_stats(data)
            result = merge_ledger_changes(
                before, data, caller="expired_recovery", trigger="expired_recovery"
            )
        except Exception as exc:
            return _fail(
                "persist_failed",
                error=str(exc),
                incomplete_ids=incomplete or None,
            )
        if result.outcome is not PersistOutcome.APPLIED:
            reason = result.reason.value if result.reason is not None else "persist_refused"
            return _fail(
                reason,
                error=reason,
                recovered=0,
                incomplete_ids=incomplete or None,
            )
        committed = set(result.committed_keys or ())
        applied_rows = [item for item in recovered_rows if _row_key(item["row"]) in committed]
        recovered = len(applied_rows)
        conflict_keys = tuple(result.conflicts or ())
        try:
            _run_effects(applied_rows)
        except Exception as exc:
            return _fail(
                "effects_incomplete",
                error=str(exc),
                recovered=recovered,
                incomplete_ids=incomplete or None,
            )
        if conflict_keys:
            return _fail(
                "persist_conflict",
                error="persist_conflict",
                recovered=recovered,
                conflicts=[list(k) if isinstance(k, tuple) else k for k in conflict_keys],
                incomplete_ids=incomplete or None,
            )

    if not dry_run and (retryable_pending or retryable_indeterminate):
        # Reload so receipt stamps from a preceding grade pass are visible.
        try:
            fresh = load_predictions(fail_closed=True)
        except Exception as exc:
            return _fail("ledger_unreadable", error=str(exc), recovered=recovered)
        pending_items = []
        for row in fresh.get("resolved") or []:
            if not isinstance(row, dict):
                continue
            effects = row.get("learning_effects") if isinstance(row.get("learning_effects"), dict) else {}
            pending = effects.get("pending") or []
            indeterminate = effects.get("indeterminate") or []
            if (pending or indeterminate) and str(row.get("outcome") or "").lower() not in _RETIRED:
                pending_items.append({
                    "row": row,
                    "actual_pct": row.get("actual_pct"),
                    "new_outcome": row.get("outcome"),
                    "correct": row.get("correct"),
                    "price": row.get("resolved_price"),
                    "resolve_at": row.get("resolved_at"),
                    "meta": {"price_source": row.get("price_source")},
                    "capture": None,
                    "expert": row.get("expert"),
                })
        if pending_items:
            try:
                _run_effects(pending_items)
            except Exception as exc:
                return _fail(
                    "effects_incomplete",
                    error=str(exc),
                    recovered=recovered,
                    incomplete_ids=incomplete or None,
                )

    if incomplete:
        if apply_lock_timed_out:
            reason = "effect_apply_lock_timeout"
        elif receipts_lock_timed_out:
            reason = "receipts_lock_timeout"
        elif receipts_write_failed:
            reason = "receipts_write_failed"
        elif effect_incomplete:
            reason = "effects_incomplete"
        else:
            reason = "judge_close_incomplete"
        return _fail(
            reason,
            error=reason,
            recovered=recovered,
            incomplete_ids=incomplete,
        )

    logger.info("expired recovery: recovered=%s skipped=%s", recovered, skipped)
    return {
        "ok": True,
        "dry_run": dry_run,
        "recovered": recovered,
        "skipped": skipped,
        "details": details[:10],
    }
