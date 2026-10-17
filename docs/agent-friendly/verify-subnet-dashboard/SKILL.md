---
name: verify-subnet-dashboard
description: Drive the Subnet Dashboard FastAPI app locally — health, readiness, and contract smoke — and capture proof artifacts. Use before claiming a route or ops slice works.
---

# Verify subnet-dashboard

## Launch

```bash
cd /workspace
source .venv/bin/activate
export DISABLE_BACKGROUND_SCANS=1
export PORT=5099
python server.py
```

Ready when log shows Uvicorn running on `0.0.0.0:5099` or `GET /health` returns `OK`.

Teardown: stop the tmux session or the shell job you started (note PID). Do not `pkill` by name.

## Doctor

```bash
curl -sf "http://127.0.0.1:${PORT:-5099}/health" | grep -q OK
curl -sf "http://127.0.0.1:${PORT:-5099}/version" | grep -q .
```

If either fails, do not drive features — fix env/venv first.

## Drive (HTTP harness)

```bash
export BASE="http://127.0.0.1:${PORT:-5099}"
curl -sf "$BASE/health"
curl -sf "$BASE/api/ops/readiness" | python -m json.tool | head
curl -sf "$BASE/api/subnets?limit=1" | python -m json.tool | head
```

Contract batch (CI parity):

```bash
DISABLE_BACKGROUND_SCANS=1 python -m pytest tests/test_endpoint_contract.py tests/test_agent_foundation_guards.py -q
```

## Evidence

Save under `/opt/cursor/artifacts/`:

- `verify-health.txt` — `/health` body
- `verify-readiness.json` — `/api/ops/readiness` body
- `verify-contract.log` — pytest output

Prove user-visible behavior (HTTP), not internal imports.

## Cleanup

Stop only the server process you launched. Keep evidence files.

## Helpers

One-shot without keeping server up:

```bash
DISABLE_BACKGROUND_SCANS=1 .venv/bin/python -c "
from fastapi.testclient import TestClient
from server import app
with TestClient(app) as c:
    assert c.get('/health').text == 'OK'
    assert c.get('/api/ops/readiness').status_code == 200
print('verify-ok')
"
```
