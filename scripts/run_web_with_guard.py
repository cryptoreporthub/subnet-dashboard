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
    _self_test = os.environ.get("RUN_WEB_WITH_GUARD_SELF_TEST", "").strip()
    if _self_test == "child_main":
        import threading

        if os.environ.get("LIVE_SUBNETS_FETCH_CHILD") != "1":
            raise SystemExit(2)
        import internal.snapshot_guard as guard

        if guard._ORIG is not None:
            raise SystemExit(3)
        if any(t.name == "learning-snapshot-prewarm" for t in threading.enumerate()):
            raise SystemExit(4)
        if "internal.learning.routes" in sys.modules:
            raise SystemExit(5)
        raise SystemExit(0)

    from internal.snapshot_guard import install

    # Spawned multiprocessing children re-import this module as __main__ on Fly;
    # never install the learning snapshot guard / prewarm thread in fetch children.
    if os.environ.get("LIVE_SUBNETS_FETCH_CHILD") != "1":
        install()

    import uvicorn

    uvicorn.run(
        "asgi_entry:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8080")),
    )
