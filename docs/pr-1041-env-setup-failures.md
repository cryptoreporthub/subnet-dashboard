# PR #1041 — environment/setup test failures

Draft review only. Do **not** merge or deploy until PR #1041 is reviewed and the `source` / `enrichment_status` semantics are accepted.

## Verdict

The four failures seen in a Cloud Agent VM with no `config/registry.json` are **environment/setup**, not a regression from the D5 metadata tagging diff.

`config/registry.json` is gitignored. Emergency-registry membership and a live `/api/subnets` row count both require that file (or a persisted universe snapshot). The metadata change does not empty `netuids` or zero `meta.total`.

## The four failures

| Test | Assertion | Why it fails here |
|------|-----------|-------------------|
| `tests/test_subnet_universe.py::test_t1_empty_state_emergency_registry` | `len(snap.netuids) > 0` | Cold boot with no persist file → `UniverseSnapshot.emergency_registry()` → `_emergency_rows()` from gitignored registry → empty |
| `tests/test_subnet_universe.py::test_cold_start_empty_tmc_emergency_registry` | `len(built.netuids) > 0` | Empty TMC success with no prior snapshot falls back to the same empty emergency registry |
| `tests/test_subnet_universe.py::test_cold_start_empty_tmc_emergency_registry_via_provider` | `len(result.netuids) > 0` | Same path via provider refresh |
| `tests/test_subnets_source_meta.py::test_subnets_meta_includes_source` | `meta.total > 0` | Live `GET /api/subnets` against empty emergency universe |

Do not skip or rewrite these tests as part of #1041. They remain valid when a registry (or LKG snapshot) is present.

## In-scope tests that did pass

Focused metadata + pump + endpoint-contract run in that session: **188 passed**, including membership-preservation (`test_build_rows_preserves_membership_netuids`) and `tests/test_endpoint_contract.py`.
