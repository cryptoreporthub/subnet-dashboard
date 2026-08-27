
# LivenessTracker — Contract Spec v1
**Repo:** cryptoreporthub/subnet-dashboard · **Authored:** 2026-08-23 (post power-hour sweep)
**Design principle:** make the lie structurally impossible, not merely discouraged. The correct-but-optional pattern (`internal/scheduler.py`) already sat unused while a weakened fork of it shipped to prod. This contract's API shape must prevent dishonesty even by accident.

---

## 1. Core invariant

> **`status == "ok"` is never a stored value. It is always *computed* from a success timestamp's freshness.**

No code path — not the scheduler itself, not a hotfix, not a copy-paste fork — can set `ok = true`. The best anyone can do is call `record_success(...)`, which writes a timestamp; whether that means "healthy" is then decided by arithmetic against wall-clock time, forever after, including after restarts.

## 2. API surface (complete)

```python
from internal.liveness import LivenessTracker

class PredictionResolverScheduler:
    def __init__(self):
        self.liveness = LivenessTracker(
            name="prediction_resolver",
            interval_seconds=300,          # expected tick cadence
            staleness_factor=2,            # ok requires success newer than 2x interval
            persist=True,                  # soul_map-backed, survives restart
        )

    def _tick(self):
        slot = heavy_job_slot("prediction_resolver")
        if slot is None:
            self.liveness.record_skip(reason="heavy_job_busy")   # FIRST-CLASS state
            return
        try:
            rows = resolve_due_predictions()
            self.liveness.record_success(                         # ONLY path toward ok
                evidence={"rows_resolved": rows, "artifact": RESOLVER_STATE_PATH},
            )
        except Exception as exc:
            self.liveness.record_failure(error=str(exc))
```

### Method-by-method rules

| Member | Rules |
|---|---|
| `__init__(name, interval_seconds, staleness_factor=2, persist=True)` | Registers itself in the global tracker registry (so `/api/liveness` can enumerate every tracker repo-wide — no scheduler can be forgotten off-list). |
| `start()` | Sets `lifecycle="started"`. Does **not** touch health. A started-but-never-succeeding tracker reads `"no_success_yet"`, never ok. |
| `record_skip(reason: str)` | Sets `last_event="skip"`, increments `consecutive_skips`, persists reason. Skips are **never** merged into ok or failure. Skips alone NEVER flip status — see the conjunction rule below. |
| `record_failure(error: str)` | Increments `consecutive_failures`; computes exponential backoff (`min(interval * 2**failures, cap)`); persists error. Status becomes `"failing"` immediately. |
| `record_success(evidence: dict)` | **Requires non-empty evidence dict** — at least one of: a positive integer count (`rows_*`, `scanned`, `ingested`), an artifact path that exists, or explicit `noop=True` for legitimately-empty cycles (logged distinctly as idle-ok). Empty `{}` raises `ValueError`. Writes `last_success_at` (UTC ISO), resets failure/skip counters, records evidence verbatim. |
| `.snapshot()` | Returns the full honest dict: `{"name", "lifecycle", "status", "status_reason", "last_success_at", "success_age_seconds", "consecutive_failures", "consecutive_skips", "backoff_seconds", "last_error", "last_skip_reason", "last_evidence"}`. |

### Computed `status`, exactly one source of truth

```
if success_age is None:                            → "no_success_yet"
elif skips >= SKIP_LIMIT and success_age > stale:  → "starved"   # conjunction — see below
elif consecutive_failures > 0:                     → "failing"
elif success_age > interval*factor:                → "stale"     # auto-degrades, unavoidable
else:                                              → "ok"
```

**Why `starved` is a conjunction, not a bare skip counter** (revised after threshold review): the dangerous false positive is a *healthy* scheduler losing the heavy-job gate several times in a row during contention, then succeeding. Under a bare-counter rule that trips a false starved alert. Under the conjunction, a contended-but-recently-successful scheduler stays `"ok"` (fresh success age), and starvation fires only when skips pile up **and** the last real success went stale — exactly the "alive but never winning the gate" signature that `stale` alone can't distinguish from "dead loop." Threshold sensitivity drops accordingly: SKIP_LIMIT becomes a secondary signal, not a hair-trigger.

**SKIP_LIMIT: derived, not guessed.** Honest admission on record: we do NOT yet have the real skip-burst distribution. The resolver's ~40-minute gaps between recorded ticks during "nominal" operation are suggestive but come from a period later determined to be degraded — calibrating "healthy skip behavior" from them would repeat tonight's unverified-numbers sin. Therefore: SKIP_LIMIT ships as config (`LIVENESS_SKIP_LIMIT`, generous default 8), the tracker persists every skip with timestamp+reason from day one, and after 7 days of production history the default is re-derived from observed p99 legitimate burst length across all trackers. Until then the conjunction makes the number safe in both directions: wrong-low just delays starved detection past stale detection; wrong-high masks starved entirely behind stale.

Note what's absent: there is no branch that consults `_running`, thread liveness, or process existence. Those may be *additional* fields, but they can never produce ok.

## 3. Persistence (cross-process honesty)

- With `persist=True`, every state change appends to the soul_map under `liveness.<name>` using the existing `write_soul_map` / `ensure_data_dir` machinery.
- On construction, the tracker **reads its own prior state back**. A freshly booted web process therefore reports the worker's real last-success age instead of inventing `null`/`stopped` (fixes loop_health contradiction, instance #5, and the hour-slot orphan display, instance #2).
- Boot-read results are tagged `"source": "persisted"` vs `"source": "inprocess"` so dashboards can tell who's talking.

## 4. Enforcement (the "mandatory" part)

1. **Conformance fixture** — `tests/helpers/liveness_conformance.py`:
   ```python
   def assert_liveness_compliant(make_scheduler):
       s = make_scheduler()
       # 1. fresh instance is never ok
       assert s.liveness.snapshot()["status"] != "ok"
       # 2. skips don't produce ok
       s.liveness.record_skip("test"); assert s.liveness.snapshot()["status"] != "ok"
       # 3. empty evidence rejected
       pytest.raises(ValueError, s.liveness.record_success, evidence={})
       # 4. stale success auto-degrades (freeze/age the timestamp)
       ...
       # 5. persistence round-trip: new tracker instance sees old success
   ```
   Every migrated scheduler gets this fixture parametrized over its factory. Copy-paste-friendly: making compliance *easy* is as important as making lying *hard*.

2. **AST guard test** — `tests/test_no_handrolled_liveness.py`: walks `internal/**/*.py`, fails CI if any module outside `internal/liveness.py` assigns `_running`, `_last_run_ok`, or returns a literal `"ok": True` inside a scheduler-shaped class. This is the teeth: a weakened fork like tonight's resolver cannot pass CI.
   **Rollout policy (stated decision, not discovered mid-PR): allowlist-shrink.** The guard ships in PR-1 with an explicit legacy allowlist naming the known hand-rolled files. Each migration PR must delete its file's entry and pass its conformance fixture, and the guard additionally asserts the allowlist is monotonically shrinking (re-adding an entry fails CI). Rationale: a single atomic multi-scheduler migration contradicts tonight's own small-slices lesson and puts the entire honesty upgrade behind one risky deploy; the allowlist makes the coexistence window explicit, bounded, and self-documenting — anyone reading the list sees exactly how much un-migrated debt remains. End-state: empty allowlist, guard fully general.

3. **Registry endpoint** — `/api/liveness` enumerates all registered trackers' snapshots. `ops/readiness.py` switches to consuming this single endpoint instead of per-scheduler ad-hoc fields (fixes the aggregation gap behind pump trust.ready).

## 5. Migration map (bounded)

| Target | Work | Also fixes |
|---|---|---|
| `council/resolver_scheduler.py` | Re-adopt base mechanics dropped in the fork; replace skip→ok block with `record_skip`. Delete the "keep tick freshness visible" comment — visibility is now honest by construction. | Instance #4 |
| `council/pick_scheduler.py` hour slot | Persist run state via tracker; kill web-orphan twin reporting (tracker persisted state shows worker truth). | Instance #2 |
| `learning/loop_health.py` | Replace `_last_resolver_tick` heuristics with registry lookup. | Instance #5 |
| `pump_alerts` trust gate | Gate `trust.ready` on `liveness.snapshot("pump_ladder").status == "ok"` (age-derived), reusing `_signal_snapshot_stale` semantics. | Instance #3 (logic change, not just instrumentation) |
| `council/selector_scheduler.py`, `calibration/scheduler.py` | Mechanical adoption. | Suspects #6–7 |
| Non-goals this PR: timeout values, FORCE_REGEN, LOOP_STALL_GUARD_KILL, fly.toml. Unchanged per standing constraint. | | |

## 6. Sequencing

1. Land `internal/liveness.py` + conformance fixture + AST guard (purely additive, zero behavior change).
2. Migrate resolver first (P0-A restart precedes or accompanies this — restarting the current launderer without fixing semantics just resumes silent starvation).
3. Hour slot + loop_health together (they share the persistence fix).
4. Pump trust gate (behavior change — expect desk automation to *stop trusting stale data*, which will look like a regression and isn't; announce in deploy notes).
5. Selector/calibration cleanup ride-along.

## 8. IMPLEMENTATION STATUS (resume kit — updated 2026-08-23 ~04:00Z)

- Path chosen: direct branch pushes outside harness (user decision).
- Branch: `liveness-tracker-pr1` · **PR #1028** (draft) → main
- Commits: `aa4f78d` (tracker+tests+guard v1) → `2bca900` (CI wiring + e2e persistence test) → guard v2 commit (attribute-aware detection, scheduler-scoped, allowlist=11)
- Pending at time of writing: CI run 32616625040 on guard v2 — **acceptance bar = green AND liveness tests verifiably executed** (they were silently skipped by v1 green; ci-smoke.yml runs a hand-listed pytest set).
- Lessons locked in: job-level green ≠ tests ran; ast.walk misses `self.x` assigns; repo-wide `"ok":True` scan false-fires on health endpoints; manual inventory missed 3 schedulers (pick_audit, indicator, pump/desk_snapshot) — found via code search, verified, allowlisted.
- Tracked follow-up: issue #1029 (pump/scheduler.py conformance before allowlist entry removal; blocks "PR-1 fully closed").
- Next after PR-1 green: PR-2 = resolver migration (delete its allowlist entry, swap skip→ok laundering block for record_skip, pass conformance fixture). Then hour slot + loop_health, pump trust gate, selector/calibration ride-along.

## 9. Post-green addendum (2026-08-23 ~05:00Z)

- CI run 32616625040 (guard v2) went **red**: `test_no_new_handrolled_liveness` flagged `internal/scheduler.py` (AdversarialScheduler) — the 12th scheduler-named module, omitted from the initial allowlist snapshot. Diagnosis was by inference (raw log download is admin-gated); falsification test = controlled one-line allowlist commit `45a87ae8`. Re-run [32618505953](https://github.com/cryptoreporthub/subnet-dashboard/actions/runs/32618505953) went green with all steps succeeding; step 7 (pytest incl. both liveness test files at that SHA) passed and later steps executed, proving exit 0.
- Standing gap: raw CI log access needs admin rights. Permanent fix option queued: diag workflow pulling job logs with the repo-scoped `GITHUB_TOKEN` and uploading them as an artifact, so future failures are read, not inferred.

## PR-2 STATUS (2026-08-23)

- resolver_scheduler migrated onto LivenessTracker (skip-first-class,
  ok derived); allowlist shrunk 12 -> 11; resolver tests added to the
  ci-smoke gate.
- Open items: migrate-vs-exempt decision for internal/scheduler.py
  reserved to issue #1032 (recommendation there is input, not default);
  remaining legacy entries tracked under the same issue.
- Diag scaffolding (diag-file-export workflow + diag/ chunks) is
  temporary and must be removed before merge to main.

## 10. ROLLOUT COMPLETE (2026-08-27)

- **PR-3 (adversarial):** `internal/scheduler.py` (AdversarialScheduler) migrated onto LivenessTracker via **PR #1075** (squash `2f2d236`), closing **#1032**. Allowlist 11 → 10.
- **PR-4 (pump):** `internal/pump/scheduler.py` (PumpLadderScheduler) migrated onto LivenessTracker via **PR #1076** (squash `947199ee`), closing **#1029**. Allowlist 10 → 9.
- Resolver migration (PR-2, #1033) landed earlier; adversarial + pump migrations complete the same-bar family.
- **Allowlist: 11 → 9**, monotonic shrink enforced by the guard; remaining 9 entries are mechanical ride-along adopters.
- Every allowlist removal was backed by: a conformance fixture (`assert_liveness_compliant`) in the file's own test suite, the test wired into `.github/workflows/ci-smoke.yml` (proving it actually ran in CI), and CI green before merge.
- **Issue #1029** — the tracked blocker for “PR-1 fully closed” — is **CLOSED**. PR-1 family complete: #1028 → #1033 → #1075 → #1076.
- Next (unchanged from §6): registry endpoint consumption (`ops/readiness.py` → `/api/liveness`), hour-slot + loop_health persistence fixes, pump trust gate behavior change, selector/calibration ride-along. End-state: empty allowlist.
