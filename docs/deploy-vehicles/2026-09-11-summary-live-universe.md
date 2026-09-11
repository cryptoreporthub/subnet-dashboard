# /api/summary live-universe deploy vehicle

This docs-only vehicle deploys the current main commit after routing /api/summary through the live subnet universe.

Included production changes:

- PR #1271: /api/summary now derives its counts from the shared/live universe (`_list_subnets_base_rows()` + `summarize_subnets`) instead of `config/registry.json`, mirroring /api/stats. Adds `universe_status` and `subnet_source` observability keys, plus the active-count/root-policy keys.
- PR #1271: `top_by_consensus` returns an honest empty list when live rows carry no council consensus, instead of a single phantom row of nulls.
- PR #1271: `staking_data` access in `get_summary` hardened against explicit nulls.

Expected post-deploy verification:

- `GET /version` equals the deployed head SHA reported by the Fly Deploy run.
- `GET /api/summary` reports `total_subnets` consistent with the live universe (~165) with `status_counts` no longer `{"unknown": N}`.
