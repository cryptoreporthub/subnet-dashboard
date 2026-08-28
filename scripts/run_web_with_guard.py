"""Web entry with the learning-snapshot guard installed before uvicorn boots.

Replaces "uvicorn server:app" in scripts/fly_web_entrypoint.sh (2026-08-10 fix).
python scripts/run_web_with_guard.py puts scripts/ on sys.path, NOT the repo root.
Without the sys.path bootstrap below, importing internal.snapshot_guard fails and
the web process dies at boot (Fly health check 5xx). Fixed 2026-08-10.

2026-08-27: serve via asgi_entry:app (transport gzip + immutable static cache,
supersedes PR #894) instead of server:app. The snapshot guard is still installed
before the app module is imported, preserving the original ordering guarantee.
"""

import os
import sys

# Repo root is two levels up from scripts/: scripts/run_web_with_guard.py
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from internal.snapshot_guard import install

install()

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "asgi_entry:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8080")),
    )
