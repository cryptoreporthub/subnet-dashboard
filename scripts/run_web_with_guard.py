"""Web entry with the learning-snapshot guard installed before uvicorn boots.

Replaces "uvicorn server:app" in scripts/fly_web_entrypoint.sh (2026-08-10 fix).
"""

import os

from internal.snapshot_guard import install

install()

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8080")),
    )
