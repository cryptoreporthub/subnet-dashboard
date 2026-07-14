"""Optional Sentry wiring — surfaces logger.warning+ when SENTRY_DSN is set."""

from __future__ import annotations

import logging
import os


def init_sentry() -> bool:
    """Initialize Sentry when SENTRY_DSN is configured. Returns True if active."""
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return False

    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration

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
    )
    return True
