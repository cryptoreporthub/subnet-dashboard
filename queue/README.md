# ARCHIVED — Architecture Epistemics queue (pin `c9449d64`)

**Status:** Closed 2026-10-05. Superseded by
[`cursor-agents-communication/audit-kit/`](../cursor-agents-communication/audit-kit/)
at pin `ce3d820013d45577333ac8aada8c0d9e97c54129`.

| Old path | New path |
|---|---|
| `queue/done/*.json` | Historical only — do not promote to Tier A without re-pin |
| `queue/open/incident-ledger.json` | `audit-kit/ledger/incidents.json` |
| New evidence bundles | `audit-kit/findings/*.json` |
| Claim index | `audit-kit/ledger/claims.json` |

Do not add new tickets here.

---

<details>
<summary>Original README (2026-09 campaign)</summary>

Canonical ledger for the subnet-dashboard architecture-epistemics
campaign. Every ticket here was verified via raw sed -n ranges,
sha256 digests cross-checked by two independent fetch routes
(Cursor local checkout + Gemini GitHub fetch), and reviewed by
Claude before being marked VERIFIED. No ticket is closed by the
agent that authored its finding.

Status values: PENDING_REVIEW | VERIFIED (code-only) |
VERIFIED (prod-observed@<ISO8601>) | NOT_OBSERVABLE | HOLD

Pin: c9449d6490231373748f19f299ed19d423a1c971
Deploy-confirmed live @ 2026-09-21T07:22:35Z and 2026-09-21T08:15:50Z

</details>
