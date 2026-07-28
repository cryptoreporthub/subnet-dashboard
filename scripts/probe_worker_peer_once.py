"""One-shot worker peer probe — used from fly machine exec on web (GHA diagnostic)."""
from __future__ import annotations

import os
import sys


def main() -> int:
    import requests

    app = os.environ.get("FLY_APP_NAME", "subnet-dashboard")
    port = os.environ.get("WORKER_HTTP_PORT", "8081")
    url = os.environ.get("WORKER_INTERNAL_URL", "").strip()
    if not url:
        url = f"http://{app}.flycast:{port}/api/ops/worker-peer"
    elif not url.endswith("/api/ops/worker-peer"):
        url = f"{url.rstrip('/')}/api/ops/worker-peer"
    try:
        r = requests.get(url, headers={"X-Worker-Proxy": "1"}, timeout=10)
        print(r.status_code, r.text[:400])
        return 0 if r.status_code == 200 else 1
    except Exception as exc:
        print("ERR", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
