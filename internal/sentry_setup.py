"""Optional Sentry wiring — surfaces logger.warning+ when SENTRY_DSN is set."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Production grouping: TaoStats /dtao/pool/latest/v1 404 (fetchers.taostats_client.py).
_TAOSTATS_STATUS_MSG = "TaoStats %s returned %d body=%s"
_TAOSTATS_POOL_LATEST_PATH = "/dtao/pool/latest/v1"

_SENSITIVE_HEADER_NAMES = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-auth-token",
        "proxy-authorization",
    }
)

_HANDLE_RE = re.compile(r"@[a-zA-Z0-9_]{3,32}")
_BEARER_RE = re.compile(r"(Bearer\s+)[^\s]+", re.IGNORECASE)
_AUTH_HEADER_RE = re.compile(r"(Authorization:\s*)([^\s,]+)", re.IGNORECASE)
_TAOSTATS_BODY_RE = re.compile(r"(body=).{0,200}", re.IGNORECASE)


def _format_logentry(logentry: dict[str, Any] | None) -> str:
    if not logentry:
        return ""
    message = logentry.get("message") or ""
    params = logentry.get("params") or ()
    if not params:
        return str(message)
    try:
        return str(message) % tuple(params)
    except (TypeError, ValueError):
        return str(message)


def _event_log_text(event: dict[str, Any]) -> str:
    """Best-effort formatted log text from logentry and top-level message."""
    parts: list[str] = []
    logentry = event.get("logentry")
    if isinstance(logentry, dict):
        formatted = _format_logentry(logentry)
        if formatted:
            parts.append(formatted)
    message = event.get("message")
    if isinstance(message, str) and message:
        parts.append(message)
    return " ".join(parts)


def _is_known_taostats_pool_latest_404(event: dict[str, Any]) -> bool:
    """Drop ingest for the known noisy TaoStats pool-latest 404 pattern only."""
    logentry = event.get("logentry")
    if isinstance(logentry, dict):
        message = logentry.get("message") or ""
        if message == _TAOSTATS_STATUS_MSG:
            params = logentry.get("params") or ()
            if len(params) >= 2:
                path, status = params[0], params[1]
                try:
                    status_int = int(status)
                except (TypeError, ValueError):
                    status_int = None
                return path == _TAOSTATS_POOL_LATEST_PATH and status_int == 404
        formatted = _format_logentry(logentry)
        if (
            "TaoStats" in formatted
            and _TAOSTATS_POOL_LATEST_PATH in formatted
            and "404" in formatted
        ):
            return True
    text = _event_log_text(event)
    return (
        "TaoStats" in text
        and _TAOSTATS_POOL_LATEST_PATH in text
        and "404" in text
    )


def _scrub_string(value: str) -> str:
    scrubbed = _HANDLE_RE.sub("[redacted-handle]", value)
    scrubbed = _BEARER_RE.sub(r"\1[redacted]", scrubbed)
    scrubbed = _AUTH_HEADER_RE.sub(r"\1[redacted]", scrubbed)
    if "TaoStats" in scrubbed and "body=" in scrubbed and "%s" not in scrubbed:
        scrubbed = _TAOSTATS_BODY_RE.sub(r"\1[redacted]", scrubbed)
    return scrubbed


def _scrub_mapping(mapping: dict[str, Any]) -> None:
    for key, value in list(mapping.items()):
        key_lower = str(key).lower()
        if key_lower in _SENSITIVE_HEADER_NAMES:
            mapping[key] = "[redacted]"
            continue
        if isinstance(value, str):
            mapping[key] = _scrub_string(value)
        elif isinstance(value, dict):
            _scrub_mapping(value)
        elif isinstance(value, list):
            _scrub_list(value)


def _scrub_list(items: list[Any]) -> None:
    for index, value in enumerate(items):
        if isinstance(value, str):
            items[index] = _scrub_string(value)
        elif isinstance(value, dict):
            _scrub_mapping(value)
        elif isinstance(value, list):
            _scrub_list(value)


def _scrub_exception_values(values: list[dict[str, Any]]) -> None:
    for entry in values:
        if not isinstance(entry, dict):
            continue
        stacktrace = entry.get("stacktrace")
        if isinstance(stacktrace, dict):
            frames = stacktrace.get("frames")
            if isinstance(frames, list):
                for frame in frames:
                    if isinstance(frame, dict) and isinstance(frame.get("vars"), dict):
                        _scrub_mapping(frame["vars"])
        value = entry.get("value")
        if isinstance(value, str):
            entry["value"] = _scrub_string(value)


def _scrub_breadcrumbs(crumbs: list[dict[str, Any]]) -> None:
    for crumb in crumbs:
        if not isinstance(crumb, dict):
            continue
        message = crumb.get("message")
        if isinstance(message, str):
            crumb["message"] = _scrub_string(message)
        data = crumb.get("data")
        if isinstance(data, dict):
            _scrub_mapping(data)


def _scrub_event(event: dict[str, Any]) -> dict[str, Any]:
    logentry = event.get("logentry")
    if isinstance(logentry, dict) and event.get("logger") == "fetchers.taostats_client":
        if logentry.get("message") == _TAOSTATS_STATUS_MSG:
            params = logentry.get("params")
            if isinstance(params, tuple) and len(params) >= 3:
                logentry["params"] = (params[0], params[1], "[redacted]")
            elif isinstance(params, list) and len(params) >= 3:
                logentry["params"] = [params[0], params[1], "[redacted]"]

    if isinstance(logentry, dict):
        message = logentry.get("message")
        if isinstance(message, str):
            logentry["message"] = _scrub_string(message)
        params = logentry.get("params")
        if isinstance(params, tuple):
            logentry["params"] = tuple(
                _scrub_string(p) if isinstance(p, str) else p for p in params
            )
        elif isinstance(params, list):
            logentry["params"] = [
                _scrub_string(p) if isinstance(p, str) else p for p in params
            ]

    request = event.get("request")
    if isinstance(request, dict):
        headers = request.get("headers")
        if isinstance(headers, dict):
            _scrub_mapping(headers)
        cookies = request.get("cookies")
        if isinstance(cookies, dict):
            for key in cookies:
                cookies[key] = "[redacted]"
        query_string = request.get("query_string")
        if isinstance(query_string, str):
            request["query_string"] = _scrub_string(query_string)
        url = request.get("url")
        if isinstance(url, str):
            request["url"] = _scrub_string(url)

    extra = event.get("extra")
    if isinstance(extra, dict):
        _scrub_mapping(extra)

    contexts = event.get("contexts")
    if isinstance(contexts, dict):
        _scrub_mapping(contexts)

    exception = event.get("exception")
    if isinstance(exception, dict):
        values = exception.get("values")
        if isinstance(values, list):
            _scrub_exception_values(values)

    breadcrumbs = event.get("breadcrumbs")
    if isinstance(breadcrumbs, dict):
        values = breadcrumbs.get("values")
        if isinstance(values, list):
            _scrub_breadcrumbs(values)

    message = event.get("message")
    if isinstance(message, str):
        event["message"] = _scrub_string(message)

    return event


def before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Filter known TaoStats noise and scrub sensitive fields before ingest."""
    if not isinstance(event, dict):
        return event
    try:
        if _is_known_taostats_pool_latest_404(event):
            return None
        return _scrub_event(event)
    except Exception:
        _LOGGER.debug("sentry before_send scrub failed", exc_info=True)
        return event


def init_sentry() -> bool:
    """Initialize Sentry when SENTRY_DSN is configured. Returns True if active."""
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return False

    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration

    release = os.environ.get("SENTRY_RELEASE", "").strip() or None

    sentry_sdk.init(
        dsn=dsn,
        integrations=[
            LoggingIntegration(
                level=logging.INFO,
                event_level=logging.WARNING,
            ),
        ],
        traces_sample_rate=0.0,
        environment=os.environ.get(
            "SENTRY_ENVIRONMENT",
            os.environ.get("FLY_APP_NAME", "development"),
        ),
        release=release,
        send_default_pii=False,
        before_send=before_send,
    )
    return True
