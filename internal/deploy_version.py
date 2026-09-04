"""Build metadata for GET /version (post-deploy receipt).

Release identity comes from the existing Fly/Docker path: Dockerfile
``ARG GIT_SHA`` → ``ENV SENTRY_RELEASE=${GIT_SHA}`` (see ``fly.yml``
``--build-arg GIT_SHA=…``). Short ``version`` is the first 7 chars of that
env value — same SHA the app already attributes to Sentry. No separate
git/subprocess lookup.
"""

from __future__ import annotations

import os
import sys


def build_version_payload() -> dict[str, str]:
    """Return deploy-receipt JSON; never raises — missing env → version unknown."""
    release = os.environ.get("SENTRY_RELEASE", "").strip()
    if release and release.lower() != "unknown":
        version = release[:7]
    else:
        version = "unknown"
    return {
        "version": version,
        "sentry_release": release,
        "python": sys.version.split()[0],
    }
