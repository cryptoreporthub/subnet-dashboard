"""One-shot worker peer probe — used from fly machine exec on web (GHA diagnostic)."""
from __future__ import annotations

import os
import sys


def main() -> int:
    import requests

    app = os.environ.get("FLY_APP_NAME", "subnet-dashboard")
    port = os.environ.get("WORKER_HTTP_PORT", "8081")
    region = os.environ.get("FLY_REGION", "").strip()
    candidates = []
    custom = os.environ.get("WORKER_INTERNAL_URL", "").strip().rstrip("/")
    if custom:
        candidates.append(custom)
    if region:
        candidates.append(f"http://worker.process.{region}.{app}.internal:{port}")
    candidates.append(f"http://worker.process.{app}.internal:{port}")
    candidates.append(f"http://{app}.flycast:{port}")

    seen = set()
    ok = 0
    for base in candidates:
        if base in seen:
            continue
        seen.add(base)
        for path in ("/health", "/api/ops/worker-peer"):
            url = f"{base}{path}"
            try:
                r = requests.get(url, headers={"X-Worker-Proxy": "1"}, timeout=3)
                print(f"OK {r.status_code} {url} {r.text[:200]!r}")
                if r.status_code == 200:
                    ok += 1
            except Exception as exc:
                print(f"ERR {url} {exc}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
