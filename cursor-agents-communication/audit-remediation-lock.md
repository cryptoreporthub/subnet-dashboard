# LOCK — Audit remediation (P0 stability + P1 security)

**Status:** IN PROGRESS  
**Branch:** `cursor/audit-remediation-p0-p1-1d2f`  
**Baseline:** `main` @ post-audit (2026-07-28)

## P0 — Production stability

| Item | Status |
|------|--------|
| `/api/ops/live` fast liveness (heartbeat + volume only) | BUILD |
| Cached + thread-pooled `/api/ops/readiness` | BUILD |
| Load-shed + rate-limit bypass for `/api/ops/live` | BUILD |

## P1 — Security

| Item | Status |
|------|--------|
| `WRITE_API_TOKEN` bearer guard on critical mutating routes | BUILD |
| `GET /api/predictions/resolved?resolve=true` gated when token set | BUILD |
| HTTPS-only webhook subscribe + private IP block | BUILD |
| `.gitignore` `.env` + `*.session` | BUILD |

## Ops

Set in Fly when ready (secrets override fly.toml):

```bash
flyctl secrets set WRITE_API_TOKEN='<random>' --app subnet-dashboard
```

## Verify

```bash
pytest tests/test_audit_remediation.py tests/test_endpoint_contract.py -q
curl -fsS https://subnet-dashboard.fly.dev/api/ops/live
```

## Next (not this PR)

- Dedicated worker machine (fly-web-worker-split v2)
- CSP / HSTS headers
- SS-TG W1 message detail tap
