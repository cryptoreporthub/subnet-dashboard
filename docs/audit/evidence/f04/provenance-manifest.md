---
evidence_package: F04
package_type: evidence-only
canonical_source_sha: e58bd17fd2b24a821c1c59a92111c4b4744f8d6a
captured_at_utc: 2026-09-30T01:54:05Z
---

# F04 evidence-only transfer manifest

This directory is an evidence-only transfer package. It contains no product
code, implementation, migration, deployment, merge, or production-action
claim.

## Chain of custody and source origins

- Capture was performed in a separate git worktree at
  `/tmp/f04-evidence-worktree`, checked out at canonical source SHA
  `e58bd17fd2b24a821c1c59a92111c4b4744f8d6a`.
- Source bytes were read from `/cursor/stores/self` and copied into this
  package. The source-store files were not edited, replaced, or deleted.
- `f04-design-brief.md` is a byte-for-byte copy of
  `/cursor/stores/self/docs/f04-design-brief.md`.
- `historical-registry.md` is an immutable, byte-for-byte copy of
  `/cursor/stores/self/internal/stale-code-repro-registry.md`.
- `derived-f04-receipt-payload.txt` was extracted from the historical
  registry's `## F04 raw receipt` `text` fenced block. It is explicitly a
  derived payload, not a standalone raw artifact.
- Transfer destination is this repository path:
  `docs/audit/evidence/f04/`.

## Package hashes and sizes

| File | Source origin | Bytes | SHA-256 |
|---|---|---:|---|
| `f04-design-brief.md` | `/cursor/stores/self/docs/f04-design-brief.md` | 35179 | `33efd2675c9e4244ef8d3680e3840e481cd544400f7ba05eacd3cb3ae4b2d50b` |
| `historical-registry.md` | `/cursor/stores/self/internal/stale-code-repro-registry.md` | 9473 | `07071ddde786519059eefc173cb61b118350c0a971ae1be49dc10e39ebd07d7c` |
| `derived-f04-receipt-payload.txt` | Exact bytes between the historical registry's F04 ` ```text ` fences | 366 | `7058129a0414f713a0ce5a4e1ab74bd2b8ff5ff96f2ece49d6a492c919fd8cc9` |
| `validation-receipt.txt` | Generated raw copy/hash/content validation output | 1041 | `93beaac99afbdf3ac6cea66a4e4eb9e6500fb9a5422d163eb95d85745089a7fb` |

The standalone raw F04 artifact is unavailable in the source store, so no
standalone raw-artifact hash can be established. The derived payload hash above
must not be conflated with the historical registry hash. The package contains
one recorded Cursor receipt and no second independent receipt.

## Pinned count convention and receipt

The exact count-convention command recorded by the current brief and registry
is:

```sh
git -C /workspace show --no-patch --format='PIN=%H%nDATE=%cI' e58bd17fd2b24a821c1c59a92111c4b4744f8d6 && printf '%s\n' '--- _save_raw matches ---' && git -C /workspace grep -n -E '_save_raw[[:space:]]*\(' e58bd17fd2b24a821c1c59a92111c4b4744f8d6 -- '*.py' && printf '%s\n' '--- write_soul_map runtime matches ---' && git -C /workspace grep -n -E 'write_soul_map[[:space:]]*\(' e58bd17fd2b24a821c1c59a92111c4b4744f8d6 -- 'internal/*.py' 'internal/**/*.py' 'scripts/*.py' && printf '%s\n' '--- test write_soul_map counts ---' && git -C /workspace grep -c -E 'write_soul_map[[:space:]]*\(' e58bd17fd2b24a821c1c59a92111c4b4744f8d6 -- 'tests/*.py'
```

Recorded receipt:

```text
F04_COUNT_CONVENTION_CHECK=PASS
canonical_sha=e58bd17fd2b24a821c1c59a92111c4b4744f8d6
_save_raw_matrix_rows=9
direct_gateway_matrix_rows=9
adapter_definition_excluded=true
gateway_definition_excluded=true
test_call_sites_excluded=true count=22
non_runtime_references_excluded=true
```

The receipt is a source-recorded count convention, not a new implementation
or production measurement.

## Explicit limitations and non-claims

- No production read, write, probe, loss, frequency, or state claim.
- No product-code change, refactor, dependency change, migration, data repair,
  deploy, restart, rollback, merge, PR, or CI/deploy action is implied by the
  evidence.
- No implementation contract, same-key winner policy, conflict policy,
  cross-process safety guarantee, or MindmapBridge preservation guarantee.
- No second independent reproduction or dual-receipt claim.
- The derived payload is not a standalone raw artifact and cannot establish a
  standalone raw-artifact hash.
- This package preserves source evidence only; it does not validate or extend
  the historical experiment.
