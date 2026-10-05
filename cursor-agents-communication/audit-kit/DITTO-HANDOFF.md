# Ditto Code handoff (mandatory before any commit)

Ditto does **not** start blind bundles until Mission Control posts a **handoff
ticket** with all required fields. No ticket = no commit.

## MC handoff ticket (paste to Ditto)

```markdown
## Ditto blind-bundle handoff

| Field | Value |
|---|---|
| **pin** | ce3d820013d45577333ac8aada8c0d9e97c54129 |
| **claim_id(s)** | e.g. SMOKE-001 (one bundle per claim_id) |
| **class** | e.g. C5 |
| **slice** | e.g. smoke-gate / C8-appendix / blind-parallel-SMOKE-001 |
| **evidence PR** | #NNNN |
| **branch** | audit/evidence-YYYY-MM-DD-<slice> |
| **parent_sha** | <current PR head SHA — parent for create_or_update_file> |
| **output path** | cursor-agents-communication/audit-kit/findings/{claim_id}.ditto.json |

**Overlap rule:** Blind parallel uses the **same logical `claim_id`** as Cursor
Lane 1 (e.g. `SMOKE-001`) but a **distinct filename**:
`findings/SMOKE-001.ditto.json` (JSON field `claim_id` still `SMOKE-001`).
MC keys contradictions on `claim_id` + `path:lines`, not filename alone.

**Ledger:** Ditto does **not** write any file under `ledger/` (including
`contradictions.json`). Flag overlaps via bundle `conflicts_with` or PR comment.
```

## Ditto authorized actions

| Action | Allowed? |
|---|---|
| `create_or_update_file` on `findings/*.json` | **YES** — only on ticket `branch`, parent = ticket `parent_sha` |
| Commit to `main` | **NO** |
| Commit to fresh branch not on the evidence PR | **NO** |
| Write `ledger/claims.json` | **NO** — MC only |
| Write `ledger/contradictions.json` | **NO** — MC only |
| Self-verify / set Tier A | **NO** |
| PR comment flagging overlap | **YES** |

## Contradiction protocol

1. Ditto publishes Tier **B** bundle on the evidence PR branch.
2. If disposition conflicts with another bundle on the same `claim_id` or
   `path:lines` span → set `conflicts_with` in JSON **or** comment on the PR.
3. **MC** adds a row to `ledger/contradictions.json` — both bundles stay Tier **B**.
4. **No auto-resolution** — neither bundle is promoted on seniority; Joshua resolves.

## Sequence (first smoke)

1. Merge audit-kit scaffold PR (#1323).
2. New Cursor Project MC runs SMOKE; Lane 1 produces Cursor bundles.
3. MC opens draft evidence PR (`audit/evidence-…`), indexes `ledger/claims.json`.
4. MC posts handoff ticket to Ditto (PR #, branch, parent_sha, claim_ids).
5. Ditto commits blind parallel bundles to **that PR head only**.
6. Replit spot-checks PR diff.
