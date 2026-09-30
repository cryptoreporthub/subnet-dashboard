---
evidence_package: F04
package_type: evidence-only
canonical_source_sha: e58bd17fd2b24a821c1c59a92111c4b4744f8d6a
captured_at_utc: 2026-09-30T02:30:00Z
revision: replit-corrections-2026-09-30
---

# F04 evidence-only transfer manifest

This directory is an evidence-only transfer package. It contains no product
code, implementation, migration, deployment, merge, or production-action
claim.

## Public copy scope and canonical preservation

- The **canonical historical record** remains
  `/cursor/stores/self/internal/stale-code-repro-registry.md` (SHA-256
  `07071ddde786519059eefc173cb61b118350c0a971ae1be49dc10e39ebd07d7c`). This
  package's `historical-registry.md` is an immutable derivative copy of that
  file. It is not edited, replaced, or retracted by later derivative work.
- `f04-design-brief.md` in this package is a **derivative F04 review copy**.
  The 2026-09-30 Replit corrections apply only to this derivative copy. They
  do **not** imply that a later commit retracts, rewrites, or supersedes prior
  public history in the source store or in PR #1316's earlier commit
  `bf3828baed74445b821512dae4314fb875da75ee`.
- Without separate authorization, reviewers must treat only this derivative
  review copy (and its validation receipt) as the narrowed correction scope.
  The canonical source-store registry and any prior public commit bytes remain
  the preserved historical record.
- No implementation, production probe, deploy, restart, rollback, merge, or PR
  change is authorized by this manifest.

## Chain of custody and source origins

- Capture was performed in a separate git worktree at
  `/tmp/f04-worktree`, based on PR #1316 head
  `bf3828baed74445b821512dae4314fb875da75ee`.
- Source bytes were read from `/cursor/stores/self`. The source-store files
  were not edited, replaced, or deleted.
- `historical-registry.md` is an immutable, byte-for-byte copy of
  `/cursor/stores/self/internal/stale-code-repro-registry.md`.
- `f04-design-brief.md` is a derivative review copy. It was sourced from
  `/cursor/stores/self/docs/f04-design-brief.md` and then corrected per
  Replit's 2026-09-30 recommendations (resolver class label, hard-termination
  scope, registry link, and public-copy boundaries). It is **not** claimed to
  be byte-for-byte equal to the source-store brief after correction.
- `derived-f04-receipt-payload.txt` was extracted from the historical
  registry's `## F04 raw receipt` fenced block using the rule below. It is
  explicitly a derived payload, not a standalone raw artifact.
- Transfer destination is this repository path: `docs/audit/evidence/f04/`.

## Derived payload extraction rule

Given the historical registry section headed `## F04 raw receipt` with a
` ```text ` fenced block:

1. Locate the opening fence line exactly ` ```text ` followed by one LF
   (U+000A).
2. Locate the closing fence line exactly one LF followed by ` ``` `.
3. The derived payload is the byte sequence **between** those fences, having
   removed exactly one LF after the opening fence and exactly one LF before
   the closing fence.
4. No additional trimming, normalization, or reformatting is permitted.

Equivalent extraction at the canonical registry copy:

```sh
python3 - <<'PY'
from pathlib import Path
text = Path('docs/audit/evidence/f04/historical-registry.md').read_text()
section = text.split('## F04 raw receipt', 1)[1]
start = section.index('```text\n') + len('```text\n')
end = section.index('\n```', start)
payload = section[start:end]
Path('docs/audit/evidence/f04/derived-f04-receipt-payload.txt').write_bytes(payload.encode())
print(f'payload_bytes={len(payload)}')
print(__import__('hashlib').sha256(payload.encode()).hexdigest())
PY
```

## Read-only provenance commands and output requirements

Reviewers must be able to reproduce provenance from read-only commands. A
manifest assertion alone is insufficient. Required checks:

```sh
# 1. Pin identity
git -C /tmp/f04-worktree show --no-patch --format='PIN=%H%nDATE=%cI' e58bd17fd2b24a821c1c59a92111c4b4744f8d6a

# 2. Registry immutability (canonical source-store vs package copy)
cmp -s /cursor/stores/self/internal/stale-code-repro-registry.md \
  /tmp/f04-worktree/docs/audit/evidence/f04/historical-registry.md
echo "registry_cmp_exit=$?"

# 3. Package hashes (record stdout exactly)
sha256sum /tmp/f04-worktree/docs/audit/evidence/f04/*

# 4. Derived payload matches registry fence bytes
python3 - <<'PY'
import hashlib
from pathlib import Path
pkg = Path('/tmp/f04-worktree/docs/audit/evidence/f04')
registry = (pkg / 'historical-registry.md').read_text()
section = registry.split('## F04 raw receipt', 1)[1]
start = section.index('```text\n') + len('```text\n')
end = section.index('\n```', start)
expected = section[start:end].encode()
actual = (pkg / 'derived-f04-receipt-payload.txt').read_bytes()
print('payload_matches_registry_fence=', actual == expected)
print('derived_payload_sha256=', hashlib.sha256(actual).hexdigest())
PY

# 5. Count convention at pin (record full stdout + exit code)
git -C /tmp/f04-worktree show --no-patch --format='PIN=%H%nDATE=%cI' e58bd17fd2b24a821c1c59a92111c4b4744f8d6 && \
printf '%s\n' '--- _save_raw matches ---' && \
git -C /tmp/f04-worktree grep -n -E '_save_raw[[:space:]]*\(' e58bd17fd2b24a821c1c59a92111c4b4744f8d6 -- '*.py' && \
printf '%s\n' '--- write_soul_map runtime matches ---' && \
git -C /tmp/f04-worktree grep -n -E 'write_soul_map[[:space:]]*\(' e58bd17fd2b24a821c1c59a92111c4b4744f8d6 -- 'internal/*.py' 'internal/**/*.py' 'scripts/*.py' && \
printf '%s\n' '--- test write_soul_map counts ---' && \
git -C /tmp/f04-worktree grep -c -E 'write_soul_map[[:space:]]*\(' e58bd17fd2b24a821c1c59a92111c4b4744f8d6 -- 'tests/*.py'
echo "count_convention_exit=$?"

# 6. Product-code scope (tracked diff only; untracked evidence paths expected)
git -C /tmp/f04-worktree diff --name-only e58bd17fd2b24a821c1c59a92111c4b4744f8d6a
echo "tracked_diff_exit=$?"
git -C /tmp/f04-worktree status --short
```

### Source-store equality limitation

- `cmp` or `sha256sum` equality between a source-store file and a package file
  is **evidence only when the command is run and its stdout/stderr and exit
  code are recorded**.
- The source store (`/cursor/stores/self`) and this package may diverge after
  derivative corrections. In that case:
  - `historical-registry.md` must remain equal to the canonical registry
    (required `cmp_exit=0`).
  - `f04-design-brief.md` is explicitly allowed to differ from the
    source-store brief once Replit corrections are applied to the derivative
    copy only.
- A reviewer who cannot run the commands above must mark provenance checks
  **UNVERIFIED**, not PASS.

## CI smoke vs F04 package validation (do not conflate)

- A green GitHub Actions `smoke` check on PR #1316 (or any PR carrying this
  evidence-only package) validates repository CI gates only. It is **not** F04
  package validation, F04 mechanism verification, or independent receipt
  verification.
- PR #1316 head `bf3828ba` recorded `smoke` conclusion `success`, while the
  non-blocking `Lint report` step emitted a failure-level annotation
  (`Process completed with exit code 1`). That lint annotation is unresolved
  CI noise relative to F04 evidence and must not be treated as F04 validation
  output.
- No HTTP `403` response in unrelated repository code or CI log lines
  constitutes F04 package validation. F04 validation is limited to the
  read-only provenance commands and content checks recorded in
  `validation-receipt.txt`.

## Package hashes and sizes

| File | Source origin | Bytes | SHA-256 |
|---|---|---:|---|
| `f04-design-brief.md` | Derivative review copy (source: `/cursor/stores/self/docs/f04-design-brief.md`, Replit corrections applied) | 36418 | `d28c01d5bcc65385be82735a1bff13227dc34c947589c924a979962b8b47cc80` |
| `historical-registry.md` | `/cursor/stores/self/internal/stale-code-repro-registry.md` | 9473 | `07071ddde786519059eefc173cb61b118350c0a971ae1be49dc10e39ebd07d7c` |
| `derived-f04-receipt-payload.txt` | Registry `## F04 raw receipt` ` ```text ` fence bytes per extraction rule | 366 | `7058129a0414f713a0ce5a4e1ab74bd2b8ff5ff96f2ece49d6a492c919fd8cc9` |
| `validation-receipt.txt` | Generated raw provenance/content validation output | 5423 | `deeaba7a7aa54ea7e578058942ba5e617c9ea932aeb0dd33faf00496625da8c8` |

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
- Hard termination during `write_soul_map` and orphan temp-file cleanup on
  restart are **UNVERIFIED**; no test is claimed.
- A green CI `smoke` conclusion is not F04 package validation.
- This package preserves source evidence only; it does not validate or extend
  the historical experiment.
