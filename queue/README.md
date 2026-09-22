# Queue

Repo-native ledger for this campaign. Tickets live in git so status does not depend on an external memory store.

## Rules

- `done/` holds closed tickets with the pin, blob, or run receipt that closed them.
- `open/` holds mapped work that is not started. Priority is the `priority` field.
- Do not mark a ticket done without a receipt in the JSON.
- Remediation tickets stay `MAPPED_PENDING_DESIGN` until a design is accepted. Do not treat them as authorization to edit product code.
- `SMOKE-001` is a read-only probe. Do not run it until the operator asks.
