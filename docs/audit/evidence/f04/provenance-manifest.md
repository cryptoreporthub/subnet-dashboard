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

- There is no explicit authorization in the available review record to publish
  the full historical registry. Therefore this current PR copy is narrowed to
  the F04-only excerpt `f04-historical-registry-excerpt.md`. The canonical
  historical record remains
  `/cursor/stores/self/internal/stale-code-repro-registry.md` (SHA-256
  `07071ddde786519059eefc173cb61b118350c0a971ae1be49dc10e39ebd07d7c`) and
  was not edited.
- `f04-design-brief.md` in this package is a **derivative F04 review copy**.
  The 2026-09-30 Replit corrections apply only to this derivative copy. They
  do **not** imply that a later commit retracts, rewrites, or supersedes prior
  public history in the source store or in PR #1316's earlier commit
  `bf3828baed74445b821512dae4314fb875da75ee`.
- Earlier public commit bytes, including the full-registry copy in commit
  `bf3828baed74445b821512dae4314fb875da75ee`, were not rewritten or retracted.
  Any history removal requires separate approval.
- No implementation, production probe, deploy, restart, rollback, merge, or PR
  change is authorized by this manifest.

## Chain of custody and source origins

- Capture was performed in a separate git worktree at
  `/tmp/f04-worktree`, based on PR #1316 head
  `bf3828baed74445b821512dae4314fb875da75ee`.
- Source bytes were read from `/cursor/stores/self`. The source-store files
  were not edited, replaced, or deleted.
- `f04-historical-registry-excerpt.md` is an immutable F04-only byte excerpt
  copied from `/cursor/stores/self/internal/stale-code-repro-registry.md`; it
  is not the full registry.
- `f04-design-brief.md` is a derivative review copy. It was sourced from
  `/cursor/stores/self/docs/f04-design-brief.md` and then corrected per
  Replit's 2026-09-30 recommendations (resolver class label, hard-termination
  scope, registry link, and public-copy boundaries). It is **not** claimed to
  be byte-for-byte equal to the source-store brief after correction.
- `derived-f04-receipt-payload.txt` was extracted from the F04-only registry
  excerpt's fenced block using the rule below. It is
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
import hashlib
registry = Path('docs/audit/evidence/f04/f04-historical-registry-excerpt.md').read_bytes()
start = registry.index(b'```text\n') + len(b'```text\n')
end = registry.index(b'\n```', start)
payload = registry[start:end]
Path('docs/audit/evidence/f04/derived-f04-receipt-payload.txt').write_bytes(payload)
print(f'payload_bytes={len(payload)}')
print(hashlib.sha256(payload).hexdigest())
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
  /tmp/f04-worktree/docs/audit/evidence/f04/f04-historical-registry-excerpt.md
echo "full_registry_cmp_exit=$? (expected 1: current PR copy is F04-only)"

# 3. Package hashes (record stdout exactly)
sha256sum /tmp/f04-worktree/docs/audit/evidence/f04/*

# 4. Derived payload matches registry fence bytes
python3 - <<'PY'
import hashlib
from pathlib import Path
pkg = Path('/tmp/f04-worktree/docs/audit/evidence/f04')
registry = (pkg / 'f04-historical-registry-excerpt.md').read_bytes()
start = registry.index(b'```text\n') + len(b'```text\n')
end = registry.index(b'\n```', start)
expected = registry[start:end]
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
  - `f04-historical-registry-excerpt.md` is intentionally only the F04 suffix,
    so a full-registry equality check is expected to return `cmp_exit=1`.
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
- For smoke run `36671087327`, the conclusion is successful, but a
  failure-level annotation remains from the non-blocking Black step. The
  retrieved job output was:
  `black --check --line-length 88 server.py internal tests` failed with
  `540 files would be reformatted, 198 files would be left unchanged`.
  This is CI evidence only, not F04 package validation.
- The smoke result is separate from F04 package validation. F04 validation is
  limited to the read-only provenance commands and content checks recorded in
  `validation-receipt.txt`.

## F04 evidence-chain sign-off

**BLOCKED.** The standalone raw artifact is unavailable, its standalone hash
cannot be established, and provenance cannot be independently completed from
the current source materials. This package does not claim F04 completion.

## Package hashes and sizes

| File | Source origin | Bytes | SHA-256 |
|---|---|---:|---|
| `f04-design-brief.md` | Derivative review copy (source: `/cursor/stores/self/docs/f04-design-brief.md`, Replit corrections applied) | 36455 | `aa5786dba6bc1921ef6b6b97aa8cb1d6c709a116eb69da6e4d49769a56f8a603` |
| `f04-historical-registry-excerpt.md` | F04-only excerpt from `/cursor/stores/self/internal/stale-code-repro-registry.md` | 645 | `6a82494203d0afdb8ee4424dece8e127f70fd80a5f2ab81ac36789e78869684c` |
| `derived-f04-receipt-payload.txt` | Registry `## F04 raw receipt` ` ```text ` fence bytes per extraction rule | 366 | `7058129a0414f713a0ce5a4e1ab74bd2b8ff5ff96f2ece49d6a492c919fd8cc9` |
| `validation-receipt.txt` | Generated raw provenance/content validation output | 3206 | `0b86939d4ea0eb936d3618f706b7f26b0d0abbcb3d8dad751e7f49d8e736b8ed` |

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
