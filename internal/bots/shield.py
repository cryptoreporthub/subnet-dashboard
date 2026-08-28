"""Read-only security and abuse detection bot (Shield).

Shield observes request telemetry, classifies risk per Policy §3.1, and
proposes remediations.  It never blocks, rate-limits, revokes credentials, or
otherwise mutates production state.  Every state-changing recommendation is
gated by ``approval_for(action_category="security", state_changing=True)``
(security_operator / security_review_queue).

Policy §3.1 risk classes (exact; no ``info`` class):
    low | medium | high | critical

Mapping used by the four monitors (in-repo; not a parallel taxonomy):
- low     — isolated burst 429s, method mismatch, thin missing-header signal
- medium  — sustained over-limit traffic, scraping/enumeration, path probing
- high    — repeated write/scan/trigger hits, clustered 401s on write-auth
- critical — credential-stuffing scale 401s / many distinct failed tokens

Policy §4 evidence hygiene: attributed request_logs envelopes via
``classify_freshness`` / ``aggregate_freshness``, no fabricated findings when
telemetry is missing, secrets redacted through ``internal.ops.notify``.
Uncertain or false-positive-looking detections are kept and marked
``needs_review`` rather than dropped or auto-blocked.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from internal.ops.bot_policy import (
    approval_for,
    classify_freshness,
    with_bot_contract,
)
from internal.ops.notify import notify, redact
from internal.rate_limit import (
    default_limit,
    is_exempt_path,
    rate_limit_enabled,
    strict_limit,
)
from internal.write_auth import _path_protected, write_auth_enabled

BOT_NAME = "shield"

# Policy §3.1 — exact set.  Every finding.risk is one of these four.
RISK_CLASSES = ("low", "medium", "high", "critical")
_RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

_MONITORS = ("rate_limits", "scraping", "endpoint_misuse", "auth_abuse")

_BROWSER_HEADER_KEYS = ("user-agent", "accept")
_CRAWLER_UA_RE = re.compile(
    r"bot|crawler|spider|scrape|wget|curl|python-requests|go-http-client|libwww",
    re.IGNORECASE,
)
_PROBE_PATH_RE = re.compile(
    r"(?:/\.env(?:\.|$)|/admin(?:/|$)|/wp-|/phpinfo|/debug(?:/|$)|/server-status|/api/internal)",
    re.IGNORECASE,
)
_SCAN_TRIGGER_RE = re.compile(r"/(?:scan|trigger)(?:/|$)", re.IGNORECASE)
_INVESTIGATE_RE = re.compile(r"^/api/investigate(?:/|$)", re.IGNORECASE)
_DIGIT_RE = re.compile(r"/\d+")

_UNCERTAIN_CONFIDENCE = 0.5

# Burst window vs the slowapi minute budget in internal/rate_limit.py.
_BURST_SECONDS = 10.0


def _utcnow_z(now: Optional[datetime] = None) -> str:
    stamp = now or datetime.now(timezone.utc)
    return stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _parse_limit(spec: str) -> Tuple[int, float]:
    """Interpret a slowapi spec such as ``120/minute`` → (count, window_seconds)."""
    raw = (spec or "").strip().lower()
    count_s, _, unit = raw.partition("/")
    try:
        count = int(count_s)
    except ValueError:
        count = 120
    windows = {
        "second": 1.0,
        "seconds": 1.0,
        "minute": 60.0,
        "minutes": 60.0,
        "hour": 3600.0,
        "hours": 3600.0,
        "day": 86400.0,
        "days": 86400.0,
    }
    return max(1, count), windows.get(unit.strip() or "minute", 60.0)


def _headers(event: Mapping[str, Any]) -> Dict[str, str]:
    raw = event.get("headers") or {}
    if not isinstance(raw, Mapping):
        return {}
    return {str(k).lower(): "" if v is None else str(v) for k, v in raw.items()}


def _client_ip(event: Mapping[str, Any], headers: Mapping[str, str]) -> str:
    """Match Fly X-Forwarded-For first-hop keying used by rate_limit._fly_client_ip."""
    forwarded = (headers.get("x-forwarded-for") or "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    for key in ("ip", "client_ip", "remote_addr"):
        value = str(event.get(key) or "").strip()
        if value:
            return value
    return "unknown"


def _status_of(event: Mapping[str, Any]) -> Optional[int]:
    raw = event.get("status", event.get("status_code"))
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _path_of(event: Mapping[str, Any]) -> str:
    path = event.get("path") or event.get("url") or ""
    path = str(path)
    if path.startswith("http://") or path.startswith("https://"):
        from urllib.parse import urlparse

        parsed = urlparse(path)
        path = parsed.path or "/"
        if not event.get("query") and parsed.query:
            return path
    return path or "/"


def _query_of(event: Mapping[str, Any], path: str) -> str:
    query = event.get("query") or event.get("query_string") or ""
    if query:
        return str(query)
    if "?" in str(event.get("url") or ""):
        return str(event.get("url")).split("?", 1)[1]
    if "?" in path:
        return path.split("?", 1)[1]
    return ""


def _normalize(event: Any, index: int) -> Optional[Dict[str, Any]]:
    if not isinstance(event, Mapping):
        return None
    headers = _headers(event)
    path = _path_of(event).split("?", 1)[0] or "/"
    query = _query_of(event, str(event.get("path") or event.get("url") or ""))
    method = str(event.get("method") or "GET").upper()
    ts = _parse_utc(event.get("ts") or event.get("timestamp") or event.get("time"))
    auth = headers.get("authorization") or headers.get("x-write-api-token") or ""
    token_present = bool(auth.strip())
    token_fingerprint = ""
    if token_present:
        # Count uniqueness without retaining the secret (Policy §4).
        token_fingerprint = hashlib.sha256(auth.encode("utf-8")).hexdigest()[:12]
    return {
        "index": index,
        "ts": ts,
        "ip": _client_ip(event, headers),
        "method": method,
        "path": path,
        "query": query,
        "status": _status_of(event),
        "headers": headers,
        "token_present": token_present,
        "token_fingerprint": token_fingerprint,
        "error": str(event.get("error") or ""),
        "exempt": is_exempt_path(path),
        "protected": _path_protected(method, path, query),
    }


def _bucket(ts: Optional[datetime], width: float, origin: datetime) -> int:
    if ts is None:
        return 0
    return int((ts - origin).total_seconds() // width)


def _has_browser_headers(headers: Mapping[str, str]) -> bool:
    return all(str(headers.get(name) or "").strip() for name in _BROWSER_HEADER_KEYS)


def _confidence(
    *,
    event_count: int,
    complete_headers: bool,
    freshness_status: str,
    timestamps_complete: bool,
) -> float:
    score = 0.45
    if event_count >= 20:
        score += 0.3
    elif event_count >= 8:
        score += 0.22
    elif event_count >= 3:
        score += 0.12
    if complete_headers:
        score += 0.15
    if timestamps_complete:
        score += 0.08
    else:
        score -= 0.12
    if freshness_status in ("missing", "degraded"):
        score = min(score, 0.4)
    elif freshness_status == "stale":
        # Stale logs are attributed but too old to act on without review.
        score = min(score, 0.45)
    return max(0.05, min(1.0, round(score, 2)))


def _needs_review(
    confidence: float,
    freshness_status: str,
    *,
    false_positive: bool = False,
) -> Tuple[bool, Optional[str]]:
    reasons: List[str] = []
    if false_positive:
        reasons.append("false_positive_candidate")
    if confidence < _UNCERTAIN_CONFIDENCE:
        reasons.append("low_confidence")
    if freshness_status in ("missing", "degraded"):
        reasons.append("incomplete_evidence")
    elif freshness_status == "stale":
        reasons.append("stale_evidence")
    if not reasons:
        return False, None
    return True, ",".join(reasons)


def _finding(
    *,
    monitor: str,
    risk: str,
    confidence: float,
    summary: str,
    subject: Mapping[str, Any],
    evidence: Mapping[str, Any],
    action: str,
    action_detail: str,
    freshness_status: str,
    false_positive: bool = False,
) -> Dict[str, Any]:
    if risk not in _RISK_ORDER:
        # Fail closed: unknown labels are not a fifth class.
        risk = "critical"
        false_positive = False
        summary = f"{summary} (risk relabeled critical; unknown class is not Policy §3.1)"
    review, reason = _needs_review(
        confidence, freshness_status, false_positive=false_positive
    )
    approval = approval_for("security", state_changing=True)
    return {
        "id": uuid.uuid4().hex[:12],
        "monitor": monitor,
        "risk": risk,
        "confidence": confidence,
        "needs_review": review,
        "needs_review_reason": reason,
        "summary": redact(summary),
        "subject": redact(dict(subject)),
        "evidence": redact(dict(evidence)),
        "recommended_action": {
            "action": action,
            "detail": redact(action_detail),
            "state_changing": True,
            "auto_applied": False,
        },
        "approval": approval,
        "mutated": False,
        "blocked": False,
    }


def _group_by_ip(events: Sequence[Mapping[str, Any]]) -> Dict[str, List[Mapping[str, Any]]]:
    grouped: Dict[str, List[Mapping[str, Any]]] = {}
    for event in events:
        grouped.setdefault(str(event["ip"]), []).append(event)
    return grouped


def _monitor_rate_limits(
    events: Sequence[Mapping[str, Any]],
    *,
    freshness_status: str,
) -> List[Dict[str, Any]]:
    default_n, default_window = _parse_limit(default_limit())
    strict_n, _strict_window = _parse_limit(strict_limit())
    billed = [e for e in events if not e["exempt"]]
    if not billed:
        return []
    origin = min((e["ts"] for e in billed if e["ts"] is not None), default=datetime.now(timezone.utc))
    findings: List[Dict[str, Any]] = []
    enabled = rate_limit_enabled()

    for ip, rows in _group_by_ip(billed).items():
        minute_counts: Dict[int, int] = {}
        burst_counts: Dict[int, int] = {}
        status_429 = 0
        ts_ok = True
        headers_ok = True
        for row in rows:
            if row["ts"] is None:
                ts_ok = False
            if not _has_browser_headers(row["headers"]):
                headers_ok = False
            if row["status"] == 429:
                status_429 += 1
            minute_counts[_bucket(row["ts"], default_window, origin)] = (
                minute_counts.get(_bucket(row["ts"], default_window, origin), 0) + 1
            )
            burst_counts[_bucket(row["ts"], _BURST_SECONDS, origin)] = (
                burst_counts.get(_bucket(row["ts"], _BURST_SECONDS, origin), 0) + 1
            )
        max_minute = max(minute_counts.values(), default=0)
        max_burst = max(burst_counts.values(), default=0)
        over_minute_windows = sum(1 for count in minute_counts.values() if count > default_n)
        burst_budget = max(1, int(default_n * (_BURST_SECONDS / default_window) * 2))
        over_burst = max_burst > burst_budget or status_429 > 0
        over_strict = max_minute > strict_n
        if not over_burst and over_minute_windows == 0:
            continue

        if over_minute_windows >= 2:
            risk = "high" if over_strict or status_429 >= 10 else "medium"
            kind = "sustained"
        else:
            risk = "low"
            kind = "burst"

        conf = _confidence(
            event_count=len(rows),
            complete_headers=headers_ok,
            freshness_status=freshness_status,
            timestamps_complete=ts_ok,
        )
        action = "enable_rate_limit" if not enabled else "tighten_rate_limit"
        detail = (
            f"IP {ip} {kind} over-limit vs RATE_LIMIT_DEFAULT={default_limit()} "
            f"(strict={strict_limit()}); 429s={status_429}, max_per_minute={max_minute}. "
            "Recommend tightening the default or applying strict_limit to the hot path. "
            "Do not auto-block."
        )
        findings.append(
            _finding(
                monitor="rate_limits",
                risk=risk,
                confidence=conf,
                summary=f"{kind} rate-limit abuse from {ip} ({len(rows)} billed requests)",
                subject={"ip": ip, "kind": kind},
                evidence={
                    "source": "request_logs",
                    "event_indexes": [row["index"] for row in rows[:20]],
                    "billed_requests": len(rows),
                    "status_429": status_429,
                    "max_per_minute": max_minute,
                    "max_per_burst_window": max_burst,
                    "over_minute_windows": over_minute_windows,
                    "rate_limit_enabled": enabled,
                    "default_limit": default_limit(),
                    "strict_limit": strict_limit(),
                },
                action=action,
                action_detail=detail,
                freshness_status=freshness_status,
            )
        )
    return findings


def _path_template(path: str) -> str:
    return _DIGIT_RE.sub("/{n}", path)


def _monitor_scraping(
    events: Sequence[Mapping[str, Any]],
    *,
    freshness_status: str,
) -> List[Dict[str, Any]]:
    public_gets = [
        e
        for e in events
        if e["method"] == "GET" and not e["protected"] and e["status"] in (None, 200, 301, 302, 304)
    ]
    if not public_gets:
        return []
    findings: List[Dict[str, Any]] = []
    for ip, rows in _group_by_ip(public_gets).items():
        templates: Dict[str, set] = {}
        missing_ua = 0
        crawler = 0
        no_browser = 0
        paths = set()
        ts_ok = True
        for row in rows:
            if row["ts"] is None:
                ts_ok = False
            ua = (row["headers"].get("user-agent") or "").strip()
            if not ua:
                missing_ua += 1
            elif _CRAWLER_UA_RE.search(ua):
                crawler += 1
            if not _has_browser_headers(row["headers"]):
                no_browser += 1
            template = _path_template(row["path"])
            if "{n}" in template:
                templates.setdefault(template, set()).add(row["path"])
            paths.add(row["path"])
        max_enum = max((len(v) for v in templates.values()), default=0)
        volume = len(rows)
        if volume < 5 and max_enum < 8 and missing_ua < 5 and crawler == 0:
            continue

        crawling = max_enum >= 8 or (volume >= 15 and len(paths) >= 8)
        header_gap = no_browser >= 5 or missing_ua >= 5
        if not crawling and not header_gap and crawler == 0:
            continue

        fp = crawler > 0 and volume < 40 and max_enum < 12
        if header_gap and not crawling:
            fp = True
        if crawling and header_gap:
            risk = "high"
        elif crawling or (header_gap and volume >= 15):
            risk = "medium"
        else:
            risk = "low"

        conf = _confidence(
            event_count=volume,
            complete_headers=no_browser == 0,
            freshness_status=freshness_status,
            timestamps_complete=ts_ok,
        )
        if fp:
            # Known-crawler UAs are kept (never dropped) but flagged for review.
            conf = min(conf, 0.48)
        findings.append(
            _finding(
                monitor="scraping",
                risk=risk,
                confidence=conf,
                summary=(
                    f"scraping pattern from {ip}: volume={volume}, "
                    f"enum={max_enum}, missing_ua={missing_ua}"
                ),
                subject={"ip": ip},
                evidence={
                    "source": "request_logs",
                    "event_indexes": [row["index"] for row in rows[:20]],
                    "public_get_count": volume,
                    "distinct_paths": len(paths),
                    "max_enumeration": max_enum,
                    "missing_user_agent": missing_ua,
                    "crawler_ua_count": crawler,
                    "missing_browser_headers": no_browser,
                    "templates": sorted(templates)[:8],
                },
                action="review_ip",
                action_detail=(
                    f"Review IP {ip} for scraping; consider tightening RATE_LIMIT_DEFAULT "
                    "on public GET surfaces. Do not add a blanket exempt-path exception "
                    "without security_operator approval. Do not auto-block."
                ),
                freshness_status=freshness_status,
                false_positive=fp,
            )
        )
    return findings


def _is_expensive_write(path: str, method: str) -> bool:
    if _SCAN_TRIGGER_RE.search(path):
        return True
    if _INVESTIGATE_RE.search(path) and method != "GET":
        return True
    return False


def _monitor_endpoint_misuse(
    events: Sequence[Mapping[str, Any]],
    *,
    freshness_status: str,
) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for ip, rows in _group_by_ip(events).items():
        expensive = [r for r in rows if _is_expensive_write(r["path"], r["method"])]
        probes = [r for r in rows if _PROBE_PATH_RE.search(r["path"] or "")]
        mismatches = []
        for row in rows:
            path = row["path"]
            method = row["method"]
            status = row["status"]
            if method == "GET" and _SCAN_TRIGGER_RE.search(path):
                mismatches.append(row)
            elif method not in ("GET", "HEAD", "OPTIONS") and is_exempt_path(path):
                mismatches.append(row)
            elif status == 405:
                mismatches.append(row)
        if not expensive and not probes and not mismatches:
            continue

        if len(expensive) >= 3:
            risk = "high"
            kind = "expensive_write"
        elif probes:
            risk = "medium"
            kind = "path_probe"
        else:
            risk = "low"
            kind = "method_mismatch"
        fp_candidate = kind == "method_mismatch"

        sample = expensive or probes or mismatches
        ts_ok = all(row["ts"] is not None for row in sample)
        conf = _confidence(
            event_count=len(sample),
            complete_headers=all(_has_browser_headers(row["headers"]) for row in sample),
            freshness_status=freshness_status,
            timestamps_complete=ts_ok,
        )
        token_note = (
            "WRITE_API_TOKEN is set."
            if write_auth_enabled()
            else "WRITE_API_TOKEN is unset; requiring it is the primary remediation."
        )
        action = "require_write_api_token" if not write_auth_enabled() else "review_ip"
        findings.append(
            _finding(
                monitor="endpoint_misuse",
                risk=risk,
                confidence=conf,
                summary=f"{kind} from {ip} ({len(sample)} requests)",
                subject={"ip": ip, "kind": kind},
                evidence={
                    "source": "request_logs",
                    "event_indexes": [row["index"] for row in sample[:20]],
                    "expensive_write_count": len(expensive),
                    "probe_count": len(probes),
                    "method_mismatch_count": len(mismatches),
                    "paths": sorted({row["path"] for row in sample})[:12],
                    "methods": sorted({row["method"] for row in sample}),
                },
                action=action,
                action_detail=(
                    f"Review {kind} against scan/trigger/investigate or non-public paths "
                    f"from {ip}. {token_note} Keep strict_limit on write/scan routes. "
                    "Do not auto-block."
                ),
                freshness_status=freshness_status,
                false_positive=fp_candidate,
            )
        )
    return findings


def _monitor_auth_abuse(
    events: Sequence[Mapping[str, Any]],
    *,
    freshness_status: str,
) -> List[Dict[str, Any]]:
    # write_auth.py emits 401 write_api_token_required on protected writes.
    # Unrelated 401s on public routes are not auth abuse.
    auth_fail = [
        e
        for e in events
        if e["error"] == "write_api_token_required"
        or (e["protected"] and e["status"] == 401)
        or (e["protected"] and not e["token_present"] and e["status"] in (401, None))
    ]
    if not auth_fail:
        return []
    findings: List[Dict[str, Any]] = []
    for ip, rows in _group_by_ip(auth_fail).items():
        fingerprints = {row["token_fingerprint"] for row in rows if row["token_fingerprint"]}
        missing = sum(1 for row in rows if not row["token_present"])
        count = len(rows)
        if count >= 10 or len(fingerprints) >= 5:
            risk = "critical"
        elif count >= 3:
            risk = "high"
        else:
            risk = "medium"
        ts_ok = all(row["ts"] is not None for row in rows)
        conf = _confidence(
            event_count=count,
            complete_headers=all("authorization" in row["headers"] or not row["token_present"] for row in rows),
            freshness_status=freshness_status,
            timestamps_complete=ts_ok,
        )
        if count < 3:
            conf = min(conf, 0.48)
        action = "require_write_api_token" if not write_auth_enabled() else "review_ip"
        detail = (
            f"Auth failures from {ip}: count={count}, missing_token={missing}, "
            f"distinct_presented_secrets={len(fingerprints)} (fingerprints not logged). "
            "Recommend reviewing the IP and, if stuffing is confirmed, rotating "
            "WRITE_API_TOKEN after security_operator approval. Do not auto-revoke."
        )
        findings.append(
            _finding(
                monitor="auth_abuse",
                risk=risk,
                confidence=conf,
                summary=f"write-auth abuse from {ip} ({count} failures)",
                subject={"ip": ip},
                evidence={
                    "source": "request_logs",
                    "event_indexes": [row["index"] for row in rows[:20]],
                    "failure_count": count,
                    "missing_token_count": missing,
                    "distinct_presented_secrets": len(fingerprints),
                    "paths": sorted({row["path"] for row in rows})[:12],
                    "write_auth_enabled": write_auth_enabled(),
                },
                action=action,
                action_detail=detail,
                freshness_status=freshness_status,
                false_positive=count < 3,
            )
        )
    return findings


_MONITOR_FNS = {
    "rate_limits": _monitor_rate_limits,
    "scraping": _monitor_scraping,
    "endpoint_misuse": _monitor_endpoint_misuse,
    "auth_abuse": _monitor_auth_abuse,
}


def _overall_risk(findings: Sequence[Mapping[str, Any]]) -> Optional[str]:
    if not findings:
        return None
    worst = max(findings, key=lambda item: _RISK_ORDER.get(str(item.get("risk")), 0))
    risk = str(worst.get("risk"))
    return risk if risk in _RISK_ORDER else "critical"


def _remediations(findings: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    seen = set()
    for finding in findings:
        rec = dict(finding.get("recommended_action") or {})
        key = (rec.get("action"), finding.get("subject", {}).get("ip"), finding.get("monitor"))
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "finding_id": finding.get("id"),
                "monitor": finding.get("monitor"),
                "risk": finding.get("risk"),
                "action": rec.get("action"),
                "detail": rec.get("detail"),
                "auto_applied": False,
                "approval": finding.get("approval")
                or approval_for("security", state_changing=True),
            }
        )
    return items


def run_shield(
    events: Optional[Iterable[Any]] = None,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Scan caller-supplied request events and return a serializable report.

    Pass ``events=None`` when production telemetry is unavailable.  Shield does
    not invent a log shipper; missing logs yield degraded/missing freshness and
    no fabricated findings (Policy §4 honest-empty).
    """
    started = time.perf_counter()
    run_id = uuid.uuid4().hex[:12]
    reference = now or datetime.now(timezone.utc)
    audit_ids: List[str] = [
        notify("scan_start", bot=BOT_NAME, run_id=run_id, payload={"monitors": list(_MONITORS)})
    ]
    report: Optional[Dict[str, Any]] = None
    try:
        report = _run_shield_body(
            events,
            run_id=run_id,
            audit_ids=audit_ids,
            reference=reference,
            started=started,
        )
        return report
    except Exception:
        envelope = classify_freshness("request_logs", None, now=reference, degraded=True)
        for monitor in _MONITORS:
            audit_ids.append(
                notify(
                    "skip",
                    bot=BOT_NAME,
                    run_id=run_id,
                    payload={"monitor": monitor, "reason": "scan_error"},
                )
            )
        report = with_bot_contract(
            {
                "bot": BOT_NAME,
                "run_id": run_id,
                "status": "degraded",
                "summary": "Shield scan failed; honest-empty (no fabricated findings).",
                "findings": [],
                "overall_risk": None,
                "remediations": [],
                "unknowns": ["scan_error"],
                "mutated": False,
                "blocked": False,
                "audit": {
                    "ids": audit_ids,
                    "sources_read": [],
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                },
            },
            sources=[envelope],
            confidence=None,
            action_category=None,
            state_changing=False,
            degraded=True,
        )
        return report
    finally:
        payload = {"status": "degraded", "findings": 0, "mutated": False, "blocked": False}
        if report is not None:
            payload = {
                "status": report.get("status"),
                "findings": len(report.get("findings") or []),
                "overall_risk": report.get("overall_risk"),
                "mutated": False,
                "blocked": False,
            }
        audit_ids.append(notify("scan_end", bot=BOT_NAME, run_id=run_id, payload=payload))
        if report is not None:
            report.setdefault("audit", {})["ids"] = list(audit_ids)


def _run_shield_body(
    events: Optional[Iterable[Any]],
    *,
    run_id: str,
    audit_ids: List[str],
    reference: datetime,
    started: float,
) -> Dict[str, Any]:
    if events is None:
        envelope = classify_freshness("request_logs", None, now=reference)
        for monitor in _MONITORS:
            audit_ids.append(
                notify(
                    "skip",
                    bot=BOT_NAME,
                    run_id=run_id,
                    payload={"monitor": monitor, "reason": "telemetry_missing"},
                )
            )
        return with_bot_contract(
            {
                "bot": BOT_NAME,
                "run_id": run_id,
                "status": "degraded",
                "summary": "No request logs supplied; honest-empty (no fabricated findings).",
                "findings": [],
                "overall_risk": None,
                "remediations": [],
                "unknowns": ["request_logs_unavailable"],
                "mutated": False,
                "blocked": False,
                "audit": {
                    "ids": audit_ids,
                    "sources_read": [],
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                },
            },
            sources=[envelope],
            confidence=None,
            action_category=None,
            state_changing=False,
            degraded=True,
        )

    raw_rows = list(events)
    normalized: List[Dict[str, Any]] = []
    newest = None
    unreadable = 0
    untimestamped = 0
    for index, event in enumerate(raw_rows):
        row = _normalize(event, index)
        if row is None:
            unreadable += 1
            continue
        normalized.append(row)
        if row["ts"] is None:
            untimestamped += 1
        elif newest is None or row["ts"] > newest:
            newest = row["ts"]

    logs_degraded = unreadable > 0 or untimestamped > 0
    if newest is not None and not logs_degraded:
        captured_at = _utcnow_z(newest)
    elif not raw_rows:
        captured_at = _utcnow_z(reference)
        logs_degraded = False
    else:
        captured_at = _utcnow_z(newest) if newest is not None else None
    envelope = classify_freshness(
        "request_logs",
        captured_at,
        now=reference,
        degraded=logs_degraded,
        authoritative=not logs_degraded,
    )
    freshness_status = str(envelope.get("status") or "missing")
    findings: List[Dict[str, Any]] = []
    for monitor, fn in _MONITOR_FNS.items():
        detected = fn(normalized, freshness_status=freshness_status)
        if not detected:
            audit_ids.append(
                notify(
                    "skip",
                    bot=BOT_NAME,
                    run_id=run_id,
                    payload={"monitor": monitor, "reason": "no_signal"},
                )
            )
            continue
        for finding in detected:
            findings.append(finding)
            audit_ids.append(
                notify(
                    "detection",
                    bot=BOT_NAME,
                    run_id=run_id,
                    payload={
                        "finding_id": finding["id"],
                        "monitor": monitor,
                        "risk": finding["risk"],
                        "confidence": finding["confidence"],
                        "needs_review": finding["needs_review"],
                    },
                )
            )

    remediations = _remediations(findings)
    for item in remediations:
        audit_ids.append(
            notify(
                "recommendation",
                bot=BOT_NAME,
                run_id=run_id,
                payload={
                    "finding_id": item["finding_id"],
                    "action": item["action"],
                    "risk": item["risk"],
                    "auto_applied": False,
                    "approval_status": (item.get("approval") or {}).get("status"),
                },
            )
        )

    overall = _overall_risk(findings)
    confidences = [float(f["confidence"]) for f in findings]
    rollup = min(confidences) if confidences else None
    state_changing = bool(remediations)
    unknowns: List[str] = []
    if unreadable:
        unknowns.append(f"unreadable_rows:{unreadable}")
    if untimestamped:
        unknowns.append(f"untimestamped_rows:{untimestamped}")
    if findings:
        summary = (
            f"{len(findings)} finding(s); overall_risk={overall}; "
            "recommendations only (no automatic block)."
        )
        status = "ok" if freshness_status not in ("missing", "degraded") else "degraded"
    elif not normalized and raw_rows:
        summary = "Request log rows were unreadable; no findings."
        status = "degraded"
        unknowns.append("request_logs_unreadable")
        envelope = classify_freshness("request_logs", None, now=reference, degraded=True)
    else:
        summary = "No abuse patterns detected in supplied request logs."
        status = "ok"

    return with_bot_contract(
        {
            "bot": BOT_NAME,
            "run_id": run_id,
            "status": status,
            "summary": summary,
            "findings": findings,
            "overall_risk": overall,
            "remediations": remediations,
            "unknowns": unknowns,
            "mutated": False,
            "blocked": False,
            "audit": {
                "ids": audit_ids,
                "sources_read": ["request_logs"],
                "duration_ms": int((time.perf_counter() - started) * 1000),
            },
        },
        sources=[envelope],
        confidence=rollup,
        action_category="security" if state_changing else None,
        state_changing=state_changing,
        degraded=logs_degraded or freshness_status == "degraded",
    )


class ShieldBot:
    """Thin wrapper so orchestrators can call ``ShieldBot().scan(...)``."""

    name = BOT_NAME

    def scan(
        self,
        events: Optional[Iterable[Any]] = None,
        *,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        return run_shield(events, now=now)


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Shield abuse scan (read-only; recommendations only)."
    )
    parser.add_argument(
        "events_json",
        nargs="?",
        help="JSON file of request events; omit for honest-empty missing-logs report",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    loaded: Optional[Any] = None
    if args.events_json and args.events_json != "-":
        with open(args.events_json, encoding="utf-8") as handle:
            loaded = json.load(handle)
    elif args.events_json == "-" or (args.events_json is None and not sys.stdin.isatty()):
        try:
            raw = sys.stdin.read().strip()
        except OSError:
            raw = ""
        loaded = json.loads(raw) if raw else None
    report = run_shield(loaded)
    json.dump(report, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
