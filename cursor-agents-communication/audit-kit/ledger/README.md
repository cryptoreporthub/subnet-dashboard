# Claim ledger (Mission Control merge desk)

Repo-backed **status board** for the `ce3d8200` audit. Bundles live in
[`../findings/`](../findings/); this folder indexes them for cross-agent review.

## Files

| File | Owner | Purpose |
|---|---|---|
| [`claims.json`](claims.json) | MC only | Claim index: tier, disposition, bundle path, lane, class, reviewers |
| [`contradictions.json`](contradictions.json) | MC only | Paired conflicting `claim_id`s until Joshua resolves |
| [`population.tsv`](population.tsv) | Lane 1 | 1413-file census at pin (header only until Lane 1 completes) |
| [`incidents.json`](incidents.json) | Lane 2 + MC | Incident windows A/B/C with bundle cross-links |
| [`open-questions-closure.md`](open-questions-closure.md) | MC | F02 O1–O18 → `claim_id` / evidence row / NOT_OBSERVABLE boundary |

## Status vocabulary

| Field | Values |
|---|---|
| `tier` | `B` (default) → `A` (Joshua spot-check) |
| `disposition` | `CONFIRMED` / `REFUTED` / `BY-DESIGN` / `UNKNOWN` |
| `review_status` | `pending` / `replit_pass` / `replit_modify` / `replit_block` / `merged` |
| `bundle` | Relative path under `findings/` or `null` if ledger-only stub |

## Rules

1. **MC writes `claims.json` and `contradictions.json` only** — Lane workers submit bundles; MC strip-validates schema then adds/updates rows.
2. **No Tier A without Joshua** — `tier: "A"` requires `verified_by` including `joshua` or explicit PR approval.
3. **Pin lock** — every row must match charter pin `ce3d820013d45577333ac8aada8c0d9e97c54129`.
4. **Do not reuse** old `queue/done/` claim IDs without re-pin and re-bundle.

See [`../REVIEW-WORKFLOW.md`](../REVIEW-WORKFLOW.md) and [`../DITTO-HANDOFF.md`](../DITTO-HANDOFF.md).
