# R1 pack B — redaction stratum (PLAN-v1.3)

Six **bug** fixtures (stratum only; full pack B = 36 fixtures deferred). Each case plants a logic bug in code whose **identifiers match the credential scrubber** (`token_count`, `max_tokens`, `api_key`, …) so eval measures review blind spots from `redactSecrets` on reads/diffs.

| ID | Family | Planted identifier(s) | Head symptom (oracle TBD) | Control pair |
|----|--------|----------------------|-----------------------------|--------------|
| `r1-redact-01-token-count` | boolean guard renamed | `token_count` threshold | Wrong early return when count > 0 | clean same API, no bug |
| `r1-redact-02-max-tokens` | constant assignment | `max_tokens` | Wrong cap applied to batch size | clean |
| `r1-redact-03-api-key-env` | env read | `api_key` / `API_KEY` | Missing validation on empty key | clean |
| `r1-redact-04-password-field` | struct field | `password` | Accepts blank password | clean |
| `r1-redact-05-bearer-header` | header parse | `bearer` token path | Treats missing header as success | clean |
| `r1-redact-06-secret-config` | dict key | `client_secret` | Logs/config uses wrong default | clean |

**Generator:** `generate_redaction_stratum.py` (mutations on real `internal/subnet_universe.py` paths — RUN-READY-R1PRE gate).  
**Status:** table + generator stub only; no model eval until RUN-READY-R1PRE.
