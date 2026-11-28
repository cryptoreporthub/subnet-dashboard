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

if __name__ == "__main__":
    from internal.snapshot_guard import install

    # Spawned multiprocessing children re-import this module as __main__ on Fly;
    # never install the learning snapshot guard / prewarm thread in fetch children.
    if (
        os.environ.get("LIVE_SUBNETS_FETCH_CHILD") != "1"
        and os.environ.get("RUN_MODE") != "worker"
    ):
        install()

    import uvicorn

    from internal.web_uvicorn import UVICORN_WEB_KWARGS

    # Do not read FORWARDED_ALLOW_IPS from env here — pinned in UVICORN_WEB_KWARGS.
    os.environ.pop("FORWARDED_ALLOW_IPS", None)
    asgi_target = os.environ.get("UVICORN_TARGET", "asgi_entry:app")
    uvicorn.run(
        asgi_target,
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8080")),
        **UVICORN_WEB_KWARGS,
    )
