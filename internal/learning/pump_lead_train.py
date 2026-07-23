"""Offline Upgrade-6 train prep for pump_lead (stub until n>=50).

Does not replace the hand score in prod. Collects frozen feature rows +
hit/miss labels, exports a matrix when ready, and only attempts XGBoost
when the package is installed and gradeable n meets the gate.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from internal.council.grading import is_pump_lead
from internal.file_utils import safe_read_json, safe_write_json
from internal.learning.pump_lead_features import (
    FEATURE_KEYS,
    FEATURE_SCHEMA_VERSION,
    feature_row_from_prediction,
    vector_as_list,
)

logger = logging.getLogger(__name__)

PREDICTIONS_PATH = "data/predictions.json"
MATRIX_PATH = "data/pump_lead_train_matrix.json"
MIN_TRAIN_SAMPLES = 50
# Prod hand-score replace stays gated higher (Upgrade 6 LOCK).
MIN_PROD_REPLACE = 100


def _is_gradeable_train_row(row: Dict[str, Any]) -> bool:
    if not is_pump_lead(row):
        return False
    if row.get("status") != "resolved":
        return False
    if row.get("sample_quality") == "reject":
        return False
    if row.get("outcome") in {"ungradeable", "expired", "duplicate"}:
        return False
    if row.get("correct") is None:
        return False
    return True


def collect_training_rows(
    *,
    path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return gradeable hit/miss rows with a feature vector (frozen or rebuilt)."""
    data = safe_read_json(path or PREDICTIONS_PATH, default={})
    if not isinstance(data, dict):
        return []
    resolved = list(data.get("resolved") or [])
    out: List[Dict[str, Any]] = []
    for row in resolved:
        if not isinstance(row, dict) or not _is_gradeable_train_row(row):
            continue
        feats = feature_row_from_prediction(row)
        if feats is None:
            continue
        out.append(
            {
                "id": row.get("id"),
                "netuid": row.get("netuid"),
                "correct": bool(row.get("correct")),
                "outcome": row.get("outcome"),
                "feature_schema_version": row.get(
                    "feature_schema_version", FEATURE_SCHEMA_VERSION
                ),
                "features": feats,
                "x": vector_as_list(feats),
                "y": 1 if row.get("correct") else 0,
                "had_frozen_vector": isinstance(row.get("feature_vector"), dict),
            }
        )
    return out


def dataset_status(*, path: Optional[str] = None) -> Dict[str, Any]:
    rows = collect_training_rows(path=path)
    n = len(rows)
    hits = sum(1 for r in rows if r["y"] == 1)
    misses = n - hits
    frozen = sum(1 for r in rows if r.get("had_frozen_vector"))
    return {
        "ok": True,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_keys": list(FEATURE_KEYS),
        "n": n,
        "hits": hits,
        "misses": misses,
        "frozen_feature_rows": frozen,
        "legacy_rebuilt_rows": n - frozen,
        "min_train": MIN_TRAIN_SAMPLES,
        "min_prod_replace": MIN_PROD_REPLACE,
        "ready_to_train": n >= MIN_TRAIN_SAMPLES,
        "ready_for_prod_replace": n >= MIN_PROD_REPLACE,
        "xgboost_installed": _xgboost_available(),
    }


def _xgboost_available() -> bool:
    try:
        import xgboost  # noqa: F401

        return True
    except Exception:
        return False


def export_train_matrix(
    *,
    path: Optional[str] = None,
    matrix_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Write feature matrix JSON for offline train (no model fit)."""
    rows = collect_training_rows(path=path)
    payload = {
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_keys": list(FEATURE_KEYS),
        "n": len(rows),
        "min_train": MIN_TRAIN_SAMPLES,
        "ready_to_train": len(rows) >= MIN_TRAIN_SAMPLES,
        "rows": [
            {
                "id": r["id"],
                "netuid": r["netuid"],
                "y": r["y"],
                "x": r["x"],
                "had_frozen_vector": r["had_frozen_vector"],
            }
            for r in rows
        ],
    }
    out_path = matrix_path or MATRIX_PATH
    safe_write_json(out_path, payload)
    return {
        "ok": True,
        "path": out_path,
        "n": payload["n"],
        "ready_to_train": payload["ready_to_train"],
    }


def train_offline(
    *,
    path: Optional[str] = None,
    matrix_path: Optional[str] = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Prep / optionally fit. Never swaps prod scoring.

    dry_run=True: status + would-export counts only.
    dry_run=False: export matrix; fit XGBoost only if n>=50 and package present.
    """
    status = dataset_status(path=path)
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "action": "none",
            **status,
        }

    export = export_train_matrix(path=path, matrix_path=matrix_path)
    if not status["ready_to_train"]:
        return {
            "ok": False,
            "dry_run": False,
            "action": "export_only",
            "reason": "need_more_gradeable_samples",
            "export": export,
            **status,
        }

    if not status["xgboost_installed"]:
        return {
            "ok": True,
            "dry_run": False,
            "action": "export_only",
            "reason": "xgboost_not_installed",
            "export": export,
            **status,
            "note": "Matrix exported; install xgboost later to fit. Prod hand score unchanged.",
        }

    # Fit stub — model artifact only; prod path does not load it yet.
    try:
        import xgboost as xgb

        rows = collect_training_rows(path=path)
        X = [r["x"] for r in rows]
        y = [r["y"] for r in rows]
        model = xgb.XGBClassifier(
            n_estimators=50,
            max_depth=3,
            learning_rate=0.1,
            objective="binary:logistic",
            eval_metric="logloss",
            verbosity=0,
        )
        model.fit(X, y)
        model_path = (matrix_path or MATRIX_PATH).replace(
            "train_matrix.json", "xgb_stub.json"
        )
        if model_path == (matrix_path or MATRIX_PATH):
            model_path = "data/pump_lead_xgb_stub.json"
        # Save booster as JSON (no pickle — safer for ops).
        model.get_booster().save_model(model_path)
        return {
            "ok": True,
            "dry_run": False,
            "action": "fit_stub",
            "export": export,
            "model_path": model_path,
            "prod_replace": False,
            "note": "Offline stub only — hand score still owns prod until n>=100 + explicit swap.",
            **status,
        }
    except Exception as exc:
        logger.warning("pump_lead train_offline fit failed: %s", exc)
        return {
            "ok": False,
            "dry_run": False,
            "action": "export_only",
            "reason": "fit_failed",
            "error": str(exc),
            "export": export,
            **status,
        }
