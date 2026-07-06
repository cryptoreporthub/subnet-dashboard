"""Subnet Dashboard - entry point.

Imports the app from the original monolith (server_original.py) which has
all routes, static mounts, and health endpoints intact.
"""
from server_original import app  # noqa: F401

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
