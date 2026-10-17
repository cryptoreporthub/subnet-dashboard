# Agent-friendly rearchitecture plan (subnet-dashboard)

Inverse pyramid: **structure and CI first**, static analysis second, prose last. Goal: make repeated agent mistakes fail locally before merge.

## Priority order

| P | Change | Pitfall class | Enforcement |
|---|--------|---------------|-------------|
| 1 | **Router mount registry** (`internal/routing/mount_registry.py`) and delete conditional `try/except` imports in `server.py` | Silent slice drop when import fails | `load_all()` in CI; server uses registry only |
| 2 | **Agent foundation guards** (shipped in draft PR) | Duplicate CONTRACT rows; forbidden second foundation; router flags false | `tests/test_agent_foundation_guards.py` in ci-smoke |
| 3 | **Honesty types for ops/cache** | `refresh_complete`, stale metrics, false PASS on coverage | Extend `tests/liveness_conformance.py` pattern to metrics payloads (typed `TypedDict` + contract tests) |
| 4 | **Persistence boundary** | Non-atomic JSON, tmp orphans | Require `safe_write_json` via AST allowlist (only `internal/file_utils.py` writes JSON to `data/`) |
| 5 | **Pin discipline automation** | Review at wrong SHA / branch cache | CI job: `gh pr view` head SHA printed in check summary; optional `scripts/pin_review.sh` |
| 6 | **Retire `server_original` references in tests** | Agents port from monolith copy-paste | Expand smoke pytest set; delete or quarantine modules that import removed APIs |
| 7 | **Verification skill** (store) | Agents skip real user paths | `.cursor/skills/verify-subnet-dashboard/` mirrored from store workflow |

## Architecture target (one foundation)

```text
server.py
  └── include only: lifespan, static, core HTML routes
internal/routing/mount_registry.py  ← single mount list
internal/*/routes.py                ← slice routers
tests/test_endpoint_contract.py     ← HTTP contract (behavior)
tests/test_agent_foundation_guards.py ← structural contract
```

## Prototype status

- Draft PR: agent foundation guards + mount registry loader (server.py not rewired yet).
- Next PR: replace `server.py` `include_router` block with `for name, r in load_all(): app.include_router(r)`.

## Joshua steering (high confidence)

From filtered GitHub issue comments on `cryptoreporthub/subnet-dashboard` (unsigned, bot-marker excluded; **uncertainty**: same account posts Claude/Replit/MC copy).

- Review at **pinned head** SHA before verdict.
- **pytest / contract** evidence required.
- **Honesty** semantics on partial fetch, staleness, false PASS.
- **Draft / no deploy** unless explicitly granted.

## Recall

No agent transcript JSONL on this cloud worker. Steering corroborated from GitHub comments and `cursor-agents-communication/audit-kit/REVIEW-WORKFLOW.md`.
