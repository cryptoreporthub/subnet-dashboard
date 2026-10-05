# Audit kit — Subnet Dashboard (Lanes 1 & 2)

**Entry point** for the `ce3d8200` audit. Production pin:
`ce3d820013d45577333ac8aada8c0d9e97c54129` (1413 tracked files).

## Active paths (read + write during audit)

| Path | Who writes | Purpose |
|---|---|---|
| [`subnet-dashboard-audit-brief.md`](subnet-dashboard-audit-brief.md) | Human / MC | **Charter** — scope, lanes, SMOKE, deliverables |
| [`evidence-bundle-schema.md`](evidence-bundle-schema.md) | Human | Bundle JSON shape + replay rules |
| [`REVIEW-WORKFLOW.md`](REVIEW-WORKFLOW.md) | Human | Replit verify + Ditto blind parallel |
| [`DITTO-HANDOFF.md`](DITTO-HANDOFF.md) | MC | Ticket (branch, parent_sha, PR#) before Ditto commits |
| [`findings/`](findings/) | Lane 1, Lane 2, Ditto Code | `*.json` (Cursor) / `*.ditto.json` (Ditto blind) |
| [`ledger/claims.json`](ledger/claims.json) | **MC only** | Claim index, tier, review_status |
| [`ledger/contradictions.json`](ledger/contradictions.json) | **MC only** | Conflicting bundles (both stay Tier B) |
| [`ledger/incidents.json`](ledger/incidents.json) | Lane 2 + MC | Incidents A/B/C windows |
| [`ledger/population.tsv`](ledger/population.tsv) | Lane 1 | 1413-file census |

## Reference only (read at boot; do not append during audit)

| Path | Close after |
|---|---|
| [`f-items-prior-evidence-map-2026-10-03.md`](f-items-prior-evidence-map-2026-10-03.md) | Map fold-in into ledger — then historical |
| [`f02-replit-fixlist-review-2026-10-02.md`](f02-replit-fixlist-review-2026-10-02.md) | Cited in map — no new writes |
| [`f02-runtime-audit-scope.md`](f02-runtime-audit-scope.md) | Superseded by charter Lane 2 scope |
| [`stale-code-repro-registry.md`](stale-code-repro-registry.md) | Baseline receipts — no new writes |

## Closed / do not use

| Path | Replacement |
|---|---|
| `queue/done/*.json` | `audit-kit/findings/` at `ce3d8200` |
| `queue/open/*` | `audit-kit/ledger/` |
| Gemini paste bridge | Ditto Code → evidence PR branch |

## Working rules

1. Same-turn verification — `git show <pin>:<path> | nl -ba`
2. Lane separation — Lane 1 = git tree; Lane 2 = L2.1–L2.6 envelope only
3. No Tier A without Joshua spot-check + Replit PASS on PR
4. Confirmed defects = audit output only (no product fixes in evidence PRs)

## Project model

- **Mission Control** — coordinator; owns `ledger/`; opens evidence PRs
- **Lane 1** — Tracer; C1–C13; `findings/*.json`
- **Lane 2** — ConfigTruth; incidents; `findings/*.json`
- **Ditto Code** — blind parallel; `findings/*.ditto.json` per [`DITTO-HANDOFF.md`](DITTO-HANDOFF.md)
- **Replit** — PR spot-check only

Coordination log: [`../mission-control-log.md`](../mission-control-log.md)
