# Ditto handoff — L1+L2 diagram anchor claims

**Status:** POST after Replit Batch 2 PASS on gating scopes; **do not commit before ticket is posted.**

---

## Ditto blind-bundle handoff

| Field | Value |
|---|---|
| **pin** | `ce3d820013d45577333ac8aada8c0d9e97c54129` |
| **claim_id(s)** | `SMOKE-001`, `SMOKE-002`, `C6-WORKER-HEAVY-ESSENTIAL-001`, `L2-INC-A-001`, `L2-INC-B-001`, `L2-INC-C-001`, `L2-PERSIST-HYDRATE-001` |
| **class** | C5 / C6 / C8 / L2-INC / L2-persist-hydrate |
| **slice** | architecture-map-L1L2-blind-parallel |
| **evidence PR** | #1324 |
| **branch** | `cursor/audit-evidence-2026-10-05-smoke` |
| **parent_sha** | `9bdbd003dc7097245082bcc25afd779fc18010a7` |
| **output path** | `cursor-agents-communication/audit-kit/findings/{claim_id}.ditto.json` |

**Overlap rule:** Same logical `claim_id` as Cursor Lane 1/2; distinct filename `*.ditto.json`. MC keys contradictions on `claim_id` + `path:lines`.

**Ledger:** Ditto does **not** write `ledger/*`. Flag overlaps via `conflicts_with` or PR comment.

---

## Blind parallel focus (diagram anchors)

| claim_id | Ditto re-derive |
|---|---|
| SMOKE-001 | `server.py:510-512` StaticFiles mount |
| SMOKE-002 | `resolver_scheduler.py:735-737` write_soul_map swallow |
| C6-WORKER-HEAVY-ESSENTIAL-001 | `fly.toml:41` + `background_boot.py` essential gating |
| L2-INC-A-001 | Incident A window + mechanism UNKNOWN boundary |
| L2-INC-B-001 | Incident B window + health probe receipt class |
| L2-INC-C-001 | Static burst / 47 paths / client hydrate correlation |
| L2-PERSIST-HYDRATE-001 | Persist flock + boot hydrate vs ASGI — disposition UNKNOWN unless receipt |

**Live map cross-check:** [`ledger/candidate-matrix.md`](ledger/candidate-matrix.md) master table rows for these claim_ids.

**Historical map cross-check:** REV 2.2 appendix in [`f-items-prior-evidence-map-2026-10-03.md`](f-items-prior-evidence-map-2026-10-03.md) — provenance edges only; do not treat as runtime proof.

---

## MC trigger (finish-slice)

1. Replit Batch 2 scopes A–D posted on PR #1324.
2. Gating claim_ids above at PASS (or MODIFY accepted by Joshua).
3. MC replaces `<PR head SHA>` in this ticket, posts to Ditto, appends dated line to [`mission-control-log.md`](../mission-control-log.md).
4. Ditto commits blind bundles to **PR head only** per [`DITTO-HANDOFF.md`](DITTO-HANDOFF.md).
5. Replit re-spots Ditto commits.

---

## Ditto memory mirror (optional)

Short STATUS post: `source: cursor-agents-communication`, slice `architecture-map-L1L2`, PR #1324, parent_sha, claim_id list.
