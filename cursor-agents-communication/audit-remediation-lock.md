# LOCK — Audit remediation (P0 stability + P1 security)

**Status:** DONE (phases 0–2 merged #555 #556) · phase 3 in #557  
**Branch:** `cursor/audit-remediation-p0-p1-1d2f` → merged  
**Baseline:** `main` @ `bd3a655` (2026-07-28)

## P0 — Production stability

| Item | Status |
|------|--------|
| `/api/ops/live` fast liveness (heartbeat + volume only) | **DONE** (#555) |
| Cached + thread-pooled `/api/ops/readiness` | **DONE** (#555) |
| Load-shed + rate-limit bypass for `/api/ops/live` | **DONE** (#555) |

## P1 — Security

| Item | Status |
|------|--------|
| `WRITE_API_TOKEN` bearer guard on critical mutating routes | **DONE** (#555) |
| `GET /api/predictions/resolved?resolve=true` gated when token set | **DONE** (#555) |
| HTTPS-only webhook subscribe + private IP block | **DONE** (#555) |
| `.gitignore` `.env` + `*.session` | **DONE** (#555) |
| CSP report-only + HSTS + nosniff | **DONE** (#556) |
| Sanitize API errors (message-intel) | **DONE** (#557) |

## SS-TG flagship

| Wave | Status |
|------|--------|
| W0 | **DONE** (#549) |
| W1–W3 | **#557** in flight |

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
