---
name: systems-invariants-guard
description: Use when changing persistence, JSON state loaders, locks, retry loops, or the council scorer. Checks the two failure shapes behind PR #1578 (a corrupt file read as empty, then overwritten) with a deterministic ratchet, and lists the invariants a human must still review.
---

# Systems invariants guard

## What the failure looks like

A loader hits a corrupt or unreadable file. It returns an empty container
(`[]`, `{}`). The caller then writes back, and the corrupt file, which may still
hold good history, is replaced. A missing file is fine. A torn file is not.

Two shapes cover most of PR #1578's worst bugs:

- **read-as-empty.** A handler catches more than `FileNotFoundError` and returns an empty container, in a `try` that reads.
- **swallow-to-empty.** A broad handler (`Exception`, `BaseException`, bare) assigns an empty container, in a function whose name says it writes.

## Run the checker

```bash
.venv/bin/python scripts/check_invariants.py --check   # fail on hits not in the baseline
.venv/bin/python scripts/check_invariants.py --list    # print every hit
```

`--check` exits 1 only for a NEW hit. The 38 accepted hits are in
`scripts/invariants_baseline.json`. Keys are readable (rule, file, function,
caught types, occurrence index), so they are stable across Python versions.
An `ast.dump` hash was not: the venv (3.12) and system (3.13) produced different
digests for the same source.

Regenerate the baseline only after a human has reviewed each new hit:
`--write-baseline`.

## Status per invariant (checkout at commit 1234511c)

| Invariant | Status | Anchor |
|---|---|---|
| Postmortem loader must not turn a corrupt file into "no history" before a write | **Violated.** `record` loads, appends, then saves. A corrupt file is replaced. Checker flags it. | `internal/judges/postmortems.py` `_load`, `_record_locked` |
| Retry loop must not swallow a read failure into "nothing pending" | **Violated, read-verified, not reproduced.** A corrupt postmortem file makes `list_for_judge` return `[]`, the `except` sets `existing = set()`, and `record` then saves over the file. | `internal/learning/prediction_loop.py` `retry_pending_postmortems`, `internal/judges/postmortems.py` `record` |
| Portfolio writers fail closed on an unreadable book | **Holds for writers.** Writers call `_load_checked`, which raises. The read path `_load` still returns `{}`, so read-only views can show empty. | `internal/judges/portfolios.py` `_load_checked`, `_load` |
| Watchlist store must not overwrite a corrupt document | **Violated, verified by reading.** `_read_document` returns `{}` on corrupt JSON. Checker flags it. | `internal/watchlist/store.py` `_read_document` |
| Gainers alert state must not be reset by a corrupt file | **Violated, lower severity, verified by reading.** `_read_state` returns `{}`, then `_write_state` writes. Checker flags it. | `internal/message_intel/gainers_alert.py` `_read_state` |
| Locks are not silently skipped on timeout | **Holds for `file_lock`.** It raises `TimeoutError`. `postmortems` raises `PostmortemLockTimeout`. | `internal/file_utils.py` `file_lock` |
| Atomic writes: tmp, fsync, then replace | **Holds for `safe_write_json`.** Other writers were not checked in this pass. | `internal/file_utils.py` `safe_write_json` |

"Violated" means the code as written can lose data when the file is corrupt.
It does not mean the corruption happens often.

## Scorer digest rule

`current_scorer_digest()` hashes four council files. Any change to one of them
changes the scorer's identity. It must move with `data_seeds/score_snapshots.json`
in the same commit.

- Files: `internal/council/state_vector.py`, `weights.py`, `confidence_calibration.py`, `scoring_context.py`.
- `scripts/check_commit_hygiene.py` blocks a staged scorer file without the seed.

Anchor: `internal/council/scorer_identity.py` `_SCORER_SOURCE_FILES`, `current_scorer_digest`.

## What the checker cannot see

Review these by hand. The checker is blind to them:

- Lock ordering across modules, and deadlocks between `_RECORD_LOCK` and the flock.
- Event-loop blocking in async handlers.
- Keyless ledger rows that persist without a key (a known gap on main, not re-verified in this pass).
- Whether a flagged loader's writers use the checked variant. Check each caller.
- A corrupt file that is not JSON (for example, a truncated binary).

A hit is not a verdict. A cache that treats a corrupt file as empty is fine.
Triage each new hit as: real loss (fix the loader to fail closed), cache
(accept in the baseline with a reason), or not a write path (accept).
