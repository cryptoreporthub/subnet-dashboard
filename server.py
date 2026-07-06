"""Subnet Dashboard - entry point."""
from server_original import app  # noqa: F401
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
