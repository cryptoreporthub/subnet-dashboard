"""Per-(netuid, horizon) score records: file store plus pure budget/coverage helpers.

Not wired into the live snapshot job or the request paths yet. The membership
argument to ``select_for_budget`` and ``coverage`` is the authoritative
denominator; records outside it are ignored, and it is never clipped.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

Status = Literal["ok", "failed", "excluded"]
Horizon = Literal["day", "hour"]
Key = Tuple[int, str]

STATUSES: Tuple[str, ...] = ("ok", "failed", "excluded")
HORIZONS: Tuple[str, ...] = ("day", "hour")


def key_of(record: "ScoreRecord") -> Key:
    return (record.netuid, record.horizon)


def _require_aware(moment: datetime, label: str) -> None:
    if moment.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware")


def _check_horizon(horizon: str) -> None:
    if horizon not in HORIZONS:
        raise ValueError(f"unknown horizon {horizon!r}")


def _unique_netuids(membership_netuids: Sequence[int]) -> List[int]:
    netuids = [int(n) for n in membership_netuids]
    if len(set(netuids)) != len(netuids):
        raise ValueError("membership_netuids contains duplicates")
    return netuids


@dataclass(frozen=True)
class ScoreRecord:
    netuid: int
    horizon: Horizon
    score: Optional[float]
    components: Dict[str, float]
    scored_at: datetime
    inputs_fingerprint: str
    status: Status
    reason: Optional[str] = None

    def __post_init__(self) -> None:
        _check_horizon(self.horizon)
        if self.status not in STATUSES:
            raise ValueError(f"unknown status {self.status!r}")
        _require_aware(self.scored_at, "scored_at")
        if self.status == "ok" and self.score is None:
            raise ValueError("an ok record needs a score")
        if self.status != "ok" and not self.reason:
            raise ValueError(f"a {self.status} record needs a reason")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "netuid": self.netuid,
            "horizon": self.horizon,
            "score": self.score,
            "components": dict(self.components),
            "scored_at": self.scored_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "inputs_fingerprint": self.inputs_fingerprint,
            "status": self.status,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ScoreRecord":
        score = raw.get("score")
        return cls(
            netuid=int(raw["netuid"]),
            horizon=raw["horizon"],
            score=None if score is None else float(score),
            components={str(k): float(v) for k, v in dict(raw.get("components") or {}).items()},
            scored_at=datetime.fromisoformat(str(raw["scored_at"]).replace("Z", "+00:00")),
            inputs_fingerprint=str(raw["inputs_fingerprint"]),
            status=raw["status"],
            reason=raw.get("reason"),
        )


class ScoreStore:
    """JSON file of score records keyed by (netuid, horizon).

    ponytail: single writer, no lock. Ceiling: a second concurrent writer can
    lose updates; reuse the flock pattern from score_snapshots.py if one appears.
    """

    def __init__(self, path: str) -> None:
        self.path = path

    def load(self) -> Dict[Key, ScoreRecord]:
        """Missing file is an empty store. Unreadable file is also empty, with a warning,
        which makes every name read as ``never``: low coverage, not false coverage."""
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            records = [ScoreRecord.from_dict(row) for row in raw["records"]]
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("score store %s unreadable, treating as empty: %s", self.path, exc)
            return {}
        return {key_of(record): record for record in records}

    def put_many(self, records: Iterable[ScoreRecord]) -> None:
        merged = self.load()
        for record in records:
            merged[key_of(record)] = record
        self._write(merged)

    def _write(self, records: Mapping[Key, ScoreRecord]) -> None:
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        payload = {
            "schema": 1,
            "records": [records[key].to_dict() for key in sorted(records)],
        }
        fd, tmp = tempfile.mkstemp(
            dir=directory, prefix=os.path.basename(self.path) + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def select_for_budget(
    membership_netuids: Sequence[int],
    records: Mapping[Key, ScoreRecord],
    now: datetime,
    budget_seconds: float,
    est_seconds_per_name: float,
    *,
    horizon: str = "day",
) -> List[int]:
    """Netuids to score this cycle, in order.

    Never-scored names come first (by netuid). Then every other name by
    (scored_at, netuid), failed and excluded included, so a name that always
    fails cannot hold the front of the queue. Stops before the first name that
    would exceed the estimated budget; it does not skip ahead to a cheaper one.

    ``now`` is accepted so callers pass one clock to both helpers; ordering
    does not depend on it.
    """
    _require_aware(now, "now")
    _check_horizon(horizon)
    if est_seconds_per_name <= 0:
        raise ValueError("est_seconds_per_name must be positive")
    members = _unique_netuids(membership_netuids)

    never: List[int] = []
    scored: List[ScoreRecord] = []
    for netuid in sorted(members):
        record = records.get((netuid, horizon))
        if record is None:
            never.append(netuid)
        else:
            scored.append(record)
    scored.sort(key=lambda r: (r.scored_at, r.netuid))

    chosen: List[int] = []
    spent = 0.0
    for netuid in never + [r.netuid for r in scored]:
        if spent + est_seconds_per_name > budget_seconds:
            break
        spent += est_seconds_per_name
        chosen.append(netuid)
    return chosen


@dataclass(frozen=True)
class CoverageCounts:
    membership: int
    fresh: int
    stale: int
    never: int
    failed: int
    excluded: int

    @property
    def fraction(self) -> float:
        return self.fresh / self.membership if self.membership else 0.0


def coverage(
    membership_netuids: Sequence[int],
    records: Mapping[Key, ScoreRecord],
    now: datetime,
    fresh_within_seconds: float,
    *,
    horizon: str = "day",
) -> CoverageCounts:
    """Per-state counts over the membership. Each member lands in exactly one state.

    Precedence is the record's own status: no record is ``never``, then
    ``excluded``, then ``failed``. An ``ok`` record is ``fresh`` when
    ``scored_at >= now - fresh_within_seconds``, otherwise ``stale``.
    """
    _require_aware(now, "now")
    _check_horizon(horizon)
    members = _unique_netuids(membership_netuids)
    cutoff = now - timedelta(seconds=fresh_within_seconds)
    fresh = stale = never = failed = excluded = 0
    for netuid in members:
        record = records.get((netuid, horizon))
        if record is None:
            never += 1
        elif record.status == "excluded":
            excluded += 1
        elif record.status == "failed":
            failed += 1
        elif record.scored_at >= cutoff:
            fresh += 1
        else:
            stale += 1
    return CoverageCounts(
        membership=len(members),
        fresh=fresh,
        stale=stale,
        never=never,
        failed=failed,
        excluded=excluded,
    )
