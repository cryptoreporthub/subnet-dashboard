# F04 design brief: stale whole-blob lost updates

**Status:** Design and regression-test planning only  
**Finding:** F04  
**Canonical source pin:** `e58bd17fd2b24a821c1c59a92111c4b4744f8d6a`  
**Current authorization:** Documentation and review only. No implementation,
production probe, write, restart, deploy, rollback, or PR is authorized by this
brief.

**Revision note (2026-09-29):** This documentation revision incorporates the
latest Replit PARTIAL review. It is pending named human design approval. It does
not choose an implementation contract, authorize product-code changes, or
expand the no-production gate.

**Revision note (2026-09-30):** This file is a **derivative F04 review copy**
within the evidence-only transfer package (`docs/audit/evidence/f04/`). It
incorporates Replit's recommended documentation corrections. It does not
retract, replace, or rewrite the canonical source-store record at
`/cursor/stores/self/internal/stale-code-repro-registry.md` or any prior public
history. Later edits to this derivative copy are additive documentation only.

## 1. Executive summary

F04 is a locally verified concurrency mechanism in the soul-map persistence
path. A caller can read a stale whole-document snapshot through `_load_raw`,
pause at a barrier, edit that snapshot, and pass it to `_save_raw`. Although
the final write is protected by a lock and uses an atomic replacement, the
write operation currently clears the current blob and replaces it with the
caller’s stale blob. If two writers update unrelated fields, the later writer
can silently erase the earlier writer’s update.

The recorded synthetic scenario has writer A’s update surviving while fields
labeled as unrelated conviction and resolver updates are lost. Those receipt
labels are not a claim that one real caller owns both fields; Test A uses the
pinned `save_weights`/`save_signal_weights` stale-snapshot pair and names their
actual fields. The mechanism is verified in local synthetic work only. One raw
Cursor receipt is stored; this brief makes no production data-loss claim and
does not claim two independent reproductions.

The intended design outcome is narrow: preserve unrelated concurrent updates
and make a conflicting or failed persistence operation observable. The final
implementation strategy is deliberately not chosen here.

## 2. Precise problem

At the canonical pin:

1. `internal/council/weights.py::_load_raw` delegates to
   `internal.store.soul_map_io.read_soul_map`.
2. `read_soul_map` may return a cached whole-blob snapshot within
   `SOUL_MAP_CACHE_TTL` (five seconds by default).
3. A caller edits the returned snapshot outside the persistence write lock.
4. `internal/council/weights.py::_save_raw` delegates to
   `write_soul_map` with a mutator equivalent to `blob.clear()` followed by
   `blob.update(data)`.
5. The write lock serializes the replacement, but it does not make the earlier
   read, edit, and save one atomic transaction.

The resulting sequence is:

`_load_raw` / stale snapshot → barrier → writer edits → `_save_raw` whole-blob
clear/update.

Suppose both writers load snapshot `S`. Writer A changes field `A`, and writer
B changes unrelated field `B`. If B saves first and A saves second, A's
whole-blob snapshot does not contain B, so A's write removes B. The reverse
ordering removes A. The last whole-blob saver wins, regardless of whether the
fields are unrelated.

This is distinct from a torn-file write. The atomic replace can produce valid
JSON while still losing a logically unrelated update. The existing
`write_soul_map` lock and atomic replacement therefore do not by themselves
establish lost-update safety.

The affected shape is the shared JSON document at `data/soul_map.json`,
including nested state such as:

- `adversarial_state.council_weights`;
- `adversarial_state.signal_weights`; and
- other existing top-level and nested state written by council, conviction,
  resolver, learning, and related modules.

The exact fields used for the regression fixture must be taken from the real
writer path under test. The fixture must not assume that an unknown key is
safe to delete or rewrite.

### 2A. Caller, ownership, and field matrix

This is the required source-of-truth inventory before any implementation
proposal. `UNRESOLVED` means that the current behavior is visible in source
but the cross-writer contract is not approved.

**Pinned-tree count convention (canonical SHA
`e58bd17fd2b24a821c1c59a92111c4b4744f8d6a`):**

- The `_save_raw` count is **nine application/runtime call expressions**:
  `internal/calibration/pipeline.py:78`,
  `internal/council/formula_versions.py:216`,
  `internal/council/rotation_tokens.py:92`,
  `internal/council/score_snapshots.py:735`,
  `internal/council/weights.py:576,748,868`, and
  `internal/learning/prediction_loop.py:514,585`. The
  `internal/council/weights.py:88` adapter definition is excluded from this
  call-site count.
- The direct `write_soul_map` count is **nine runtime writer call sites**:
  eight under `internal/` (the rows below, with two resolver rows) plus
  `scripts/compact_soul_map.py:123`. The
  `internal/council/weights.py:91` `_save_raw` adapter call and the
  `internal/store/soul_map_io.py:127` gateway definition are excluded from
  this direct-user count.
- Tests are excluded from both runtime counts: the pinned tree has no
  `_save_raw` test call sites and has **22 matching direct
  `write_soul_map` test call-site lines across five test files**:
  `tests/test_api_handler_timeouts.py` (1),
  `tests/test_judge_weights.py` (3),
  `tests/test_ops_readiness.py` (1),
  `tests/test_soul_map_io.py` (14), and
  `tests/test_soul_map_io_failure.py` (3).
- Tools, workflows, harness snapshots, and documentation/data references are
  excluded from runtime ownership counts. The pinned non-Python matches are
  the `.github/workflows/soul-map-compaction-dry-run.yml` comment,
  `_ci/snapshot/tests_test_resolver_scheduler.py.part-04`, and textual
  references in `cursor-agents-communication/handoff-learning-loop-mindmap-2026-08-01.md`,
  `cursor-agents-communication/phase-n-design.md`,
  `cursor-agents-communication/phase-n-safety-review.md`,
  `handoffs/liveness-tracker-spec.md`, and
  `queue/done/AUDITOR-MODIFY.json`; none is a new runtime writer row.

Therefore the matrix below contains exactly **9 `_save_raw` rows + 9 direct
gateway rows** under this convention. `write_soul_map` users below are
separate gateway call sites and must not be collapsed into the `_save_raw`
count.

| Class | Exact caller/site | Owned fields or section | Deletion semantics | List/history semantics | Legacy mirror | Section replacement |
|---|---|---|---|---|---|---|
| `_save_raw` | `internal.council.weights.save_weights` → `_save_raw` | `adversarial_state.council_weights`; `adversarial_state.last_weight_update`; root `expert_weights` | `UNRESOLVED`; omitted expert keys must not be treated as deletion without approval | Dict replacement is current local behavior; `UNRESOLVED` for concurrent key deletion | **DEFINED:** root `expert_weights` mirrors canonical council weights | No intentional section replacement; current `_save_raw` whole-blob replacement is the defect |
| `_save_raw` | `internal.council.weights.save_signal_weights` → `_save_raw` | `adversarial_state.signal_weights[horizon][signal]` | `UNRESOLVED` | Nested dict replacement is current local behavior; list semantics N/A | None identified | No intentional section replacement; whole-blob behavior is unresolved |
| `_save_raw` | `internal.council.weights.save_impact_strength` → `_save_raw` | `adversarial_state.impact_strength`; `adversarial_state.last_impact_strength_update` | `UNRESOLVED` | N/A | None identified | No intentional section replacement; whole-blob behavior is unresolved |
| `_save_raw` | `internal.council.rotation_tokens._mirror_rotation_snapshot_to_soul_map` → `_save_raw` | `soul_map_state.rotation_tokens_snapshot.tokens`; `.updated_at` | `UNRESOLVED` | `tokens` is replaced as one snapshot; append/identity/merge semantics are **UNRESOLVED** | None identified | No intentional section replacement; whole-blob behavior is unresolved |
| `_save_raw` | `internal.learning.prediction_loop._mirror_pick_to_soul_map` → `_save_raw` | `soul_map_state.last_{horizon_type}_pick.{pick,prediction_id,updated_at}` | `UNRESOLVED` | The `pick` payload may contain lists; replacement/append semantics are **UNRESOLVED** | None identified | No intentional section replacement; whole-blob behavior is unresolved |
| `_save_raw` | `internal.learning.prediction_loop.record_hold_decision` → `_save_raw` | `soul_map_state.last_{horizon_type}_pick` and `last_{horizon_type}_hold`; entry includes `action,pick,candidate,reason,updated_at` | `UNRESOLVED` | Candidate/pick payload list semantics are **UNRESOLVED**; the two latest-entry fields are replacements | None identified | No intentional section replacement; whole-blob behavior is unresolved |
| `_save_raw` | `internal.calibration.pipeline._save_calibration_state` → `_save_raw` | `adversarial_state.calibration` patch; `last_event`; `history` | Explicit deletion is **UNRESOLVED** | Current local rule appends `last_event` and retains the last five history entries; cross-writer merge/identity semantics **UNRESOLVED** | None identified | No intentional section replacement; whole-blob behavior is unresolved |
| `_save_raw` | `internal.council.formula_versions.record_calibration_version` → `_save_raw` | `adversarial_state.formula_versions.council_weights.current`; `.history` entries | `UNRESOLVED` | Current local rule retains the last 20 history entries; concurrent append/identity semantics **UNRESOLVED** | None identified | No intentional section replacement; whole-blob behavior is unresolved |
| `_save_raw` | `internal.council.score_snapshots.ScoreSnapshotScheduler._persist_cycle_summary` → `_save_raw` | `score_snapshot_scheduler.last_cycle` summary (`run_at,ok,count,written_at,path,error,skipped,phase,progress`) | `UNRESOLVED` | N/A | None identified | No intentional section replacement; whole-blob behavior is unresolved |
| direct gateway | `internal.council.mindmap_bridge.MindmapBridge._save_to_disk` → `write_soul_map` | Whole owned `soul_map_state` section from `self.soul_map_state`; whole `feedback_logs` list from `self.feedback_logs` | **UNRESOLVED**; absent keys in the in-memory section may delete newer disk keys | `learning_trail` is locally capped at 200; `feedback_logs` is a whole-list snapshot; concurrent append/identity semantics **UNRESOLVED** | None identified | **CURRENTLY YES:** replaces both owned top-level values, so section-replacement semantics require explicit approval |
| direct gateway | `internal.council.resolver_scheduler.PredictionResolverScheduler._persist_lifecycle_state` → `write_soul_map` | `prediction_resolver_scheduler.lifecycle`, `started_at`, `first_tick_scheduled_at`, `first_tick_at`, `first_tick_ok`, `lifecycle_error` | **UNRESOLVED** | N/A | None identified | No; nested field update |
| direct gateway | `internal.council.resolver_scheduler.PredictionResolverScheduler._persist_cycle_summary` → `write_soul_map` | `prediction_resolver_scheduler.last_cycle`; `.cycle_history`; `lifecycle`; `lifecycle_error`; optional `first_tick_at`, `round_robin_cursor` | **UNRESOLVED** | Current local rule appends and bounds `cycle_history` to 10; concurrent append/identity semantics **UNRESOLVED** | None identified | No; nested field update |
| direct gateway | `internal.scheduler.AdversarialScheduler._persist_cycle_summary` → `write_soul_map` | `adversarial_scheduler.last_cycle`; `emission_monitor.last_emissions`; `.snapshot_at` | **UNRESOLVED** | N/A | None identified | No; nested field update |
| direct gateway | `internal.indicators.indicator_scheduler.IndicatorScheduler._persist_cycle_summary` → `write_soul_map` | `indicator_scheduler.last_cycle` (`run_at,ok,subnets_processed,signals_emitted,error`) | **UNRESOLVED** | N/A | None identified | No; nested field update |
| direct gateway | `internal.simivision.engine._persist_convictions` → `write_soul_map` | root `simivision_convictions`; root `simivision_convictions_updated_at` | **UNRESOLVED** | The convictions mapping is replaced as a snapshot; per-subnet merge/identity semantics **UNRESOLVED** | None identified | No; root-key replacement |
| direct gateway | `internal.judges.weights.save_judge_weights` → `write_soul_map` | root `judge_weights` | **UNRESOLVED** | Dict replacement is current local behavior; concurrent key semantics **UNRESOLVED** | None identified | No; root-key replacement |
| direct gateway | `internal.liveness.LivenessTracker._save` → `write_soul_map` | dynamic `liveness.{name}`: epochs, lifecycle, failure/skip counts, errors, evidence, `updated_at` | **UNRESOLVED** | N/A | None identified | No; one named nested bucket replacement |
| direct gateway | `scripts/compact_soul_map._mutator` → `write_soul_map` | `feedback_logs` only, trimming to the last 10 when it is a list longer than 10 | **DEFINED LOCALLY:** trim-only preserves non-list values; deletion is not authorized | **DEFINED LOCALLY:** tail replacement to 10; cross-process and concurrent append semantics **UNRESOLVED** | Preserves required root keys including `expert_weights` and `simivision_convictions`; this is validation, not a mirror | No intentional section replacement; must preserve every inventoried top-level key |

The matrix deliberately distinguishes **field ownership** from **persistence
semantics**. A mutator that currently touches only its owned field is not proof
that deletion, list merge, history identity, legacy mirrors, or section
replacement have an approved contract. The nine `_save_raw` rows and the nine
direct gateway rows must each be checked against the selected design.

## 3. Scope

### In scope

- The stale read / edit / whole-blob replacement sequence around
  `_load_raw`, `_save_raw`, and `internal.store.soul_map_io`.
- Unrelated concurrent updates to the same JSON document.
- Same-process concurrency, and cross-process behavior if the selected fix
  claims to cover the worker/web split.
- Preservation of existing JSON keys and nested data shapes.
- Serialization, atomic replacement, cache, lock-timeout, malformed-input, and
  other persistence failure behavior.
- A deterministic regression test using real application writer modules and
  barriers.
- Review and authorization gates required before any implementation.

### Out of scope

- Re-designing the council, conviction, resolver, or learning algorithms.
- Changing the meaning, cadence, or thresholds of any weight or conviction
  update.
- Migrating or repairing existing production data.
- Proving how often the race occurs in production.
- Inferring production loss from the local reproduction.
- Broad storage replacement, database adoption, or a new dependency.
- Any U01 investigation or behavior change.

## 4. Required invariants

The implementation review must reject a candidate that cannot demonstrate all
of these invariants:

1. **Unrelated updates survive.** If writers update disjoint keys or disjoint
   nested paths, the final persisted document contains both updates and all
   pre-existing unrelated keys.
2. **No silent overwrite.** A stale snapshot must not silently replace a newer
   unrelated update. The system must merge the intended change, reject the
   stale operation, or otherwise return an observable conflict/error.
3. **Same-key behavior is explicit.** If two writers update the same key, the
   selected contract must define whether the result is serialized
   last-writer-wins, conflict/retry, or another policy. It must not be an
   accidental consequence of whole-blob replacement.
4. **Valid JSON remains valid JSON.** Successful writes are complete,
   parseable documents; a failed serialization or replacement does not leave a
   partial target.
5. **Unknown state is preserved.** A writer that owns one key family does not
   remove fields owned by another writer or fields added by a newer version.
6. **Cache cannot reintroduce the race.** A successful write is visible to
   subsequent reads according to the selected contract, and a stale cached
   blob is not used as the base for a destructive whole-document replacement.
7. **Failure is observable.** Lock timeout, malformed input, serialization
   failure, and replacement failure have defined caller-visible and
   log/receipt-visible outcomes.
8. **Atomicity is retained.** The fix must not trade lost logical updates for
   torn or partially written JSON.

## 5. Candidate minimal fix direction

The leading candidate to evaluate is a key-scoped merge/update or an equivalent
read-modify-write contract that applies only the caller's intended changes to
the current locked document. The final choice remains open for design review.

Candidates to evaluate include:

- **Key-scoped mutators:** have each writer provide a mutator that runs against
  a freshly loaded current blob while holding the shared lock. This is the
  clearest way to preserve unrelated keys, but requires auditing callers that
  currently pass a complete blob.
- **Intent-aware merge/update:** retain a compatibility wrapper while
  calculating and applying an explicit key/path delta. Nested dictionaries,
  deletions, list replacement, and legacy callers must have defined semantics;
  an undifferentiated recursive merge is not sufficient.
- **Versioned compare-and-swap:** record the snapshot version or digest and
  reject or retry a save when the current document changed. This avoids silent
  overwrite but requires a caller-visible conflict contract and retry limits.

Any candidate must also decide whether a write base is always reloaded from
disk under the file lock, or whether cache entries carry a validated version
that is safe for cross-process use. A process-local freshness TTL is not a
conflict protocol.

No candidate is approved by this document. Design review must select one
contract, document same-key behavior, and identify every caller whose current
whole-blob semantics would change.

## 6. Concurrency regression-test plan

The regression must use the real modules at the canonical pin and a temporary
JSON path. It must not use production `data/soul_map.json`, a live service, or
a hand-rolled replacement for the application writer.

### Test A — deterministic stale-snapshot reproduction

Use the exact real writer pair traced at the canonical pin, not hand-written
whole-blob edits:

- **Writer A:** `internal.council.weights.save_weights`, with a unique
  `quant` value. Its expected owned changes are
  `adversarial_state.council_weights.quant`,
  `adversarial_state.last_weight_update`, and the required legacy mirror
  `expert_weights.quant`.
- **Writer B:** `internal.council.weights.save_signal_weights`, with unique
  values for the `hour` and `day` signal maps. Its expected owned change is
  `adversarial_state.signal_weights`, keyed by horizon and signal name.

This is a **council-weights-versus-signal-weights** fixture, not a
conviction fixture and not a resolver-cycle fixture. Do not label
`adversarial_state.signal_weights` as `simivision_convictions` or
`prediction_resolver_scheduler` state. If conviction or resolver preservation
is also tested, use a separate named variant with the exact writer:
`internal.simivision.engine._persist_convictions` for root
`simivision_convictions` plus `simivision_convictions_updated_at`, or
`PredictionResolverScheduler._persist_cycle_summary` for
`prediction_resolver_scheduler.last_cycle` and bounded `cycle_history`.

Use a temporary soul-map document containing the canonical nested state plus an
unrelated sentinel key. The seed must include the fields needed to observe
`save_weights`'s root `expert_weights` mirror.

Coordinate two writer threads as follows:

1. Seed the file and clear any path-specific cache state.
2. Instrument the test seam around the real `_load_raw` calls so both writers
   complete their reads before either writer saves. Use a `threading.Barrier`
   with a finite timeout.
3. Have each real writer edit a different key/path. Force a deterministic save
   order so writer B saves first and writer A saves second.
4. Read the final file through the real reader and parse the on-disk JSON.
5. Assert that A's council-weight update **and root `expert_weights` mirror**,
   B's `adversarial_state.signal_weights` values for both horizons, the
   sentinel, and all required enclosing objects are present. In the separate
   conviction or resolver variant, assert the exact fields named above.

At the unmodified canonical pin, the reproduction receipt should show the
known lost-update behavior. After an implementation is separately approved,
the same test must pass with both updates present. The test must capture
thread exceptions and re-raise them in the main test thread; a deadlocked
barrier is a failure, not a skipped test.

### Test B — reverse ordering

Repeat Test A with A saving first and B saving second. This distinguishes a
real merge/conflict fix from a test that merely preserves one hard-coded
writer order. Both disjoint updates must survive.

### Test C — repeated deterministic schedule

Run the same barrier-controlled schedule repeatedly with unique values per
iteration. Assert that no iteration loses an unrelated update and that the
file remains parseable after every successful write. Use bounded iterations and
finite barrier/join timeouts so a failure cannot hang the test runner.

### Test D — same-key contract

Run two concurrent `internal.council.weights.save_weights` calls, each
targeting the same `quant` key with different values. Assert the explicitly
chosen policy:

- a documented serialized result, if last-writer-wins is retained; or
- an observable conflict/retry result, if compare-and-swap is selected.

The test must observe both `adversarial_state.council_weights.quant` and the
root `expert_weights.quant` mirror. The expected winning value or conflict
result is intentionally **UNRESOLVED** until design review selects the
same-key policy. The test must not accept an arbitrary value merely because
one thread happened to finish last.

### Test E — process boundary, if claimed

If the fix claims to cover separate web and worker processes, repeat the
disjoint-key schedule in two child processes using a filesystem-backed
temporary document and an inter-process barrier/event. Assert both updates,
valid JSON, and no silent conflict. If the fix is intentionally same-process
only, state that limitation in the design and do not imply worker/web safety.

Cross-process coverage is a blocker until the proposal states these
assumptions: all processes use the same resolved path and filesystem; the lock
is an OS-visible advisory lock rather than only a process-local mutex; atomic
replacement is visible to other processes; temporary files are created on the
same filesystem; and a process-local cache cannot be treated as a
cross-process freshness/version protocol. The required test uses two child
processes with separate module imports, the real writer pair, a finite
inter-process barrier/event, forced save order, and direct post-write disk
parsing. It must also exercise a lock timeout and cache/disk disagreement if
cross-process safety is claimed. Without these assumptions and this test,
cross-process safety remains **UNRESOLVED** and the contract must be limited
to the tested same-process scope.

The cache contract must be explicit if cross-process safety is claimed:
process-local cache entries are hints, never the cross-process authority. A
writer must base its mutation on the current locked document from disk, or on a
cache entry carrying a validated cross-process version/digest. After a
successful replacement, the writing process may refresh its own cache, but
another process must revalidate against disk (or an equivalent shared version)
before using its cached blob as a write base. TTL expiry alone is insufficient,
and a cache hit must never authorize destructive whole-blob replacement.

### Test F — regression compatibility

Retain or adapt the existing `tests/test_soul_map_io.py` coverage for:

- serialized concurrent increments performed inside the gateway;
- atomic successful writes;
- independent read copies and cache behavior;
- per-path locking;
- preservation of unrelated top-level keys; and
- failed replacement not poisoning the cache.

The new stale-caller tests are required because gateway-only increments do not
exercise a caller that reads, waits, edits, and later submits a stale whole
blob.

### Test G — MindmapBridge stale section/list snapshot (separate scope)

`MindmapBridge._save_to_disk` is a distinct direct-gateway risk: it writes its
in-memory `soul_map_state` section and `feedback_logs` list as whole values.
That stale section/list snapshot risk is **not** covered by the `_save_raw`
whole-blob regression guarantees in Tests A–D. Its list truncation and
section-replacement semantics must not be inferred from those tests.

If this risk is included later, add a separate real-module temporary-path test
with two bridge instances (or one stale bridge instance and a concurrent
gateway writer): force one instance to load, let the other update a distinct
`soul_map_state` key or `feedback_logs` entry, then save the stale instance.
Assert the selected section/list policy, preserved unrelated fields, valid
JSON, and caller-visible failure behavior under bounded barriers. Until that
test and its ownership contract are separately approved, this brief explicitly
excludes MindmapBridge section/list preservation from its guarantees.

## 7. Serialization and persistence failure behavior

The selected contract must specify behavior before implementation begins:

| Failure | Target file | Cache | Temporary file | Caller-visible result |
|---|---|---|---|---|
| Mutator raises before serialization | Unchanged | Unchanged | Absent after cleanup | Original exception or structured failure reaches the caller; no success-shaped blob |
| Value cannot be JSON serialized | Prior complete document remains | Unchanged | Removed; cleanup failure is itself reported | Serialization exception or structured failure is visible |
| `os.replace` (or equivalent) fails | Prior complete document remains | Not advanced to failed value | Removed where possible; cleanup outcome is reported | Replacement exception or structured failure is visible |
| Lock acquisition times out | Unchanged; no unlocked fallback | Unchanged | Absent | Timeout is visible to the caller; no unlocked whole-blob write |
| Existing JSON is malformed | Unchanged; no overwrite | Not replaced by an empty object | Absent | Parse failure is visible, or an explicitly approved recovery result is distinguishable from success |
| Existing JSON is a non-object | Unchanged; no overwrite | Not replaced by an empty object | Absent | Type/schema failure is visible; no silent coercion to `{}` |
| Existing JSON is unreadable | Unchanged; no overwrite | Unchanged | Absent | Read failure is visible; no stale-success result |
| Cache and disk disagree | Must use a defined version/freshness rule; never destructive cache-base replacement | Must not advance from an uncommitted value | Absent | Conflict/stale-base result is distinguishable from successful persistence |
| Process terminates during write | Prior or new complete document only | Must not claim an uncommitted value | Orphan temp file may remain; no restart cleanup mechanism evidenced at pin | Hard termination/recovery **UNVERIFIED**; no test claimed; target must remain parseable if present |

Existing behavior that catches I/O failures and returns a prior blob must be
reviewed for ambiguity: a return value that looks like a successful document
must not make a failed persistence operation appear successful to callers.
The implementation proposal must name the return/error contract and update
tests accordingly; this brief does not choose it.

The caller-visible column is a requirement, not a claim about current behavior.
In particular, the resolver, bridge, liveness, and scheduler callers currently
contain broad exception handling in some paths; design review must decide
whether those paths re-raise, return a structured failure, or emit a
distinguishable failure receipt. Swallowing a failure while returning a
success-shaped document is not an acceptable contract.

### Required failure-test contract

Before implementation approval, the proposal must choose and document one
consistent caller-facing form—propagated typed exception or structured failure
result—for every persistence failure. It must not return the prior document,
an empty object, or a success-shaped result as if the requested write
committed. A successful result is permitted only after serialization,
replacement, and the selected cache-commit step complete. The failure tests
must assert both the selected caller-facing form and these outcomes:

- mutator exception: target and cache unchanged; no temporary file;
- JSON serialization failure: prior target retained; cache unchanged;
  temporary file removed;
- replacement failure: prior target retained; cache not advanced; temporary
  file cleanup observed;
- lock timeout: no target/cache/temp mutation and no unlocked fallback;
- malformed, non-object, or unreadable input: fail closed without coercing to
  `{}` or returning a stale success;
- cache/disk disagreement: conflict or revalidation outcome is distinguishable
  from a committed success;
- hard termination during write: no orphan-temp cleanup on restart is promised
  unless an existing mechanism is separately evidenced; recovery behavior
  remains **UNVERIFIED** and is not claimed by any current test.

At the canonical pin, `write_soul_map` unlinks a temp file in a `finally`
block during the normal in-process path (`internal/store/soul_map_io.py:177-179`).
No separate restart-time orphan cleanup is evidenced. Hard termination and
post-crash recovery are therefore **UNVERIFIED** and must not be inferred from
the in-process cleanup path.

## 8. Compatibility and data-shape concerns

- Preserve the current JSON object shape and canonical key locations unless a
  separately approved migration is required.
- Preserve unknown top-level keys and unknown nested keys. They may belong to a
  newer writer or a feature not loaded by the current process.
- Do not recursively merge lists, histories, trails, or append-only records
  without an explicit ownership rule. A list may require replacement,
  append-with-identity, or conflict handling rather than concatenation.
- Define deletion explicitly. A missing key in a stale caller's snapshot must
  not be interpreted as an instruction to delete a key added by another
  writer.
- Keep legacy readers and writers able to consume the existing
  `adversarial_state` shape during rollout.
- Preserve numeric normalization, timestamp fields, and existing compatibility
  mirrors such as root-level legacy weight fields.
- Audit all `_load_raw`/`_save_raw` callers before changing their semantics.
  Callers that intentionally replace or remove a complete owned section need
  an explicit section-level operation rather than an accidental global clear.
- Keep the atomic temporary-file replacement and shared lock guarantees. A
  merge fix that bypasses the established gateway is not acceptable.

## 9. Evidence acceptance bar

An implementation proposal is not ready for approval unless its evidence
includes:

- the full canonical SHA
  `e58bd17fd2b24a821c1c59a92111c4b4744f8d6a`;
- an isolated checkout identity and `git rev-parse HEAD`;
- complete clean-tree output, including ordinary and ignored/untracked state;
- interpreter version and complete relevant dependency state;
- exact test commands, raw stdout/stderr, and exit codes;
- relevant module paths and source/blob hashes where provenance matters;
- a pre-fix receipt that demonstrates the stale whole-blob loss at the declared
  local scope;
- a post-fix receipt from the same real-module barrier schedule showing both
  unrelated updates survive;
- reverse-order and failure-path results;
- explicit same-key, malformed-input, serialization-failure, cache, and
  process-boundary conclusions;
- no network or production access in local synthetic testing; and
- an explicit boundary stating what remains unverified.

The existing evidence package contains one **registry-embedded Cursor receipt
payload** for local F04 mechanism verification. It is not a standalone raw
artifact and is not a runnable reproduction. The stored payload is linked in
[`f04-historical-registry-excerpt.md`](f04-historical-registry-excerpt.md)
(F04-only derivative excerpt of the
canonical source-store registry; canonical record preserved at
`/cursor/stores/self/internal/stale-code-repro-registry.md`),
under **F04 raw receipt**. It records the pin, exit code, final JSON fields,
lost-update booleans, empty thread errors, and clean-tree result. This brief
identifies the stored receipt. A positive local existence/identity check also
found `receipt_exists=true`, section heading `F04 raw receipt`, the canonical
pin, `EXIT=0`, and the registry SHA-256
`07071ddde786519059eefc173cb61b118350c0a971ae1be49dc10e39ebd07d7c`.
The digest covers the registry file, not an independently extracted receipt
blob. This brief does **not** claim independent verification, two independent
reproductions, production data loss, or production frequency.
A passing local regression is evidence for the tested code path only.

## 10. Review and authorization gates

1. **Design review gate:** A named human reviews this brief, the exact writer
   paths, the caller/ownership/field matrix, the invariants, and the proposed
   test schedule. Open questions, failure-result semantics, cross-process
   assumptions, and same-key semantics must be resolved or explicitly left as
   blockers. This revision remains pending that named human approval.
2. **Implementation gate:** Any code implementation requires a separate,
   explicit approval after design review. That approval must name the owner,
   files, selected contract, test scope, and non-goals. This brief does not
   grant it.
3. **Local verification gate:** Approved implementation work must use an
   isolated checkout at the canonical pin (or a clearly recorded descendant),
   temporary synthetic state, blocked outbound network, bounded tests, and no
   production reads or writes.
4. **Independent review gate:** A reviewer must inspect the diff and receipts
   for silent whole-blob replacement, accidental data-shape changes, and
   incomplete failure handling. A green test alone is not sufficient.
5. **Merge/deploy gate:** Merge, restart, rollback, and deployment require
   their own explicit authorization and the repository's existing CI/deploy
   checks. No production action is part of this design step.

## 11. Rollout and rollback considerations

If implementation is later authorized:

- Prefer a code-only rollout with no data migration or rewrite. The existing
  JSON key shape should remain readable by old and new code.
- Roll out only after the deterministic local race and persistence-failure
  tests pass, followed by the relevant repository test gates.
- Make persistence failures and conflict/retry outcomes measurable and
  distinguish them from ordinary successful writes before relying on rollout
  health signals.
- Do not use rollout as an excuse to repair, compact, backfill, or rewrite
  existing soul-map data.
- If rollback is required, revert the code path without using rollback to
  overwrite the JSON document. The pre-fix code retains the known race, so a
  rollback is a controlled exception requiring an explicit owner and
  follow-up decision.
- Preserve the failed-write document and receipt for review. Do not silently
  retry with a full-blob replacement after a conflict or persistence failure.

No rollout or rollback action is authorized now.

## 12. Explicit non-goals for this step

- No production probe, production read, production write, or production-loss
  claim.
- No product-code fix, refactor, dependency change, or workaround.
- No deploy, restart, rollback, migration, or data repair.
- No PR creation, merge, or CI/deploy action.
- No U01 changes, re-test, reinterpretation, or scope expansion.
- No final implementation choice before design review.

Any code implementation requires a separate explicit approval after this design
brief is reviewed and accepted.
