# Stale-code repro registry — v1.7

## Phase 0 close-out — path A (2026-09-29)

**Disposition:** **CLOSED as a non-production evidence phase.** Authorized evidence is complete for path A, with residuals carried forward; this is not a claim that all findings are closed.

- **U01:** locally verified tested synthetic paths; no production narrowing, post-shrink HTTP, or exact 48-hour claim.
- **F04:** locally verified stale whole-blob lost-update mechanism; no production-loss claim.
- **F01:** **PARTIAL by deliberate scope choice**; production growth remains unknown.
- **F02:** **VERIFIED only at source-static termination-path scope**; runtime/environment/orchestrator boundaries remain open.
- **F08:** **BLOCKED** pending the historical run artifact/log.
- **F03/F05/F06/F07:** **PARKED**.

This close-out adds **no production read, fix, deployment, or runtime claim**. Existing authorized evidence in this registry is preserved without expansion.

## Final audit roll-up — 2026-09-29

**Date note:** This close-out is dated **2026-09-29** because UTC rolled over
after the 2026-09-28 evidence runs. All source-pin and evidence dates remain
unchanged.

- **F02 — VERIFIED only at source-static termination-path scope.** Runtime, environment, and orchestrator boundaries remain open.
- **F04 — locally verified stale whole-blob lost-update mechanism.** The registry contains one recorded Cursor raw receipt; no second independent raw receipt is present, so no two-independent-repro claim is made. This is not a production data-loss conclusion.
- **U01 — locally verified tested synthetic paths:** fresh/no-persisted-LKG through the real local HTTP route returned `200` with `75` rows; a separate seven-day-negative synthetic `100→75` path ran through provider/persistence/feed only. No production narrowing, post-shrink HTTP, or exact 48-hour boundary is claimed.
- **F01 — PARTIAL by deliberate scope choice;** production growth remains unknown.
- **F08 — BLOCKED.**
- **F03/F05/F06/F07 — PARKED.**

Choosing F04 versus U01 is a future product/remediation scope decision, not an audit conclusion. No fix, deployment, production action, or authorization is added.

### Auditable evidence references

- **F02:** the source-static evidence is the **F02 raw receipt** below, together with the pinned source sweep recorded in that receipt.
- **F01:** the source-structure artifact is `internal/f01-local-entry-structure-2026-09-28.md`; the recorded production census is the **F01-census** section in this registry.
- **F04:** the stored Cursor evidence is the **F04 raw receipt** below.
- **U01:** the evidence is the addendum `internal/u01-provenance-addendum.md` and the independent Replit receipt `internal/replit-u01-verification-2026-09-28.md`.

The current package contains **one raw F04 receipt**. It does **not** claim two independent reproductions.

| ID | Role | SHA | Command | Exit | Result | Status |
|----|------|-----|---------|------|--------|--------|
| F01-census | executor (Cursor) | e58bd17f… | flyctl machine exec 7841024b3712e8 ls/df/census | 0 | total_bytes=850530 FL=10; full 10-key table in audit graph | **recorded** |
| F01-step2 | verifier (Replit) | e58bd17f… | code-only writers @ pin | — | 9 _save_raw; decision tree | recorded |
| F01 | finder | e58bd17f… | pytest test_oversize_legacy_array_trims_on_load | 0 | 1 passed | recorded |
| F01-entry-bound | verifier | e58bd17f… | source inspection `mindmap_bridge.py:154-203`, compaction `scripts/compact_soul_map.py:37-78` | 0 | no per-entry byte/depth/field-count bound; whole-file envelope only | recorded |
| F01-entry-structure-local | verifier (Cursor) | e58bd17fd2b24a821c1c59a92111c4b4744f8d6a | pinned `git rev-parse`/`git grep` source receipt + local `test -f data/soul_map.json` | source 0; local file 1; pinned path 128 | generated local state absent; fixed outer/nested writer shapes and count-only caps; no per-entry byte/depth/field-count cap | **recorded; source scope only** |
| F08-backup | verifier | e58bd17f… | source inspection compaction script/workflow | 0 | `copy2` preserves source mtime; equality checks mean zero-byte path could not pass against nonempty source; exact run-artifact role unknown | recorded |
| U01 | verifier (Cursor + independent Replit) | e58bd17fd2b24a821c1c59a92111c4b4744f8d6a | clean detached worktree + loaded-module path/SHA receipts + fresh/no-prior builder→provider→feed/API and actual local `/api/subnets` traces; separate seven-day-negative synthetic 100→75 provider/persistence/feed path; Replit receipt in `internal/replit-u01-verification-2026-09-28.md` | first isolated import 1 (`ModuleNotFoundError: requests`); corrected run 0 / HTTP run 0 | Fresh/no-prior path carried 75 netuids `0..74` through provider/feed/API and actual local route HTTP 200 with 75 rows; separate synthetic path covered provider/persistence/feed only | **locally verified tested synthetic paths; no production narrowing, post-shrink HTTP, or exact 48-hour boundary claimed** |
| F03/F05/F06/F07 | verifier | | pending / rerun-once | | | **parked** |
| F04 | verifier (Cursor execution) | e58bd17fd2b24a821c1c59a92111c4b4744f8d6a | real `_load_raw`/barrier/`_save_raw` + `write_soul_map` two-writer script | 0 | A update survived; B conviction and resolver updates lost; no errors; clean tree | **locally verified mechanism; one Cursor raw receipt; no prod-loss or two-independent-repro claim** |
| F02 | verifier (Replit) | e58bd17fd2b24a821c1c59a92111c4b4744f8d6a | pinned `git grep` direct-exit/process-termination sweep, tracked source/config, tests/harness excluded | 0 | direct `os._exit(1)` at loop stall guard; worker SIGTERM/SIGINT + `sys.exit(0)`; web entrypoint `kill`/restart; CI/scripts also match | **VERIFIED only at source-static termination-path scope; runtime/environment/orchestrator boundaries open** |

**Baseline:** 897245 B / FL=10 (2026-09-08); G1 observations 900585 (+5m), 901696 (+15m)  
**Prod sample:** 850530 B / FL=10 (2026-09-28 16:46 UTC) — no net increase above observed tolerance at this sample  
**Stop limit:** 5 MB (not triggered). The production raw census output is recorded in audit-graph v1.7; it is not checked into the repository or artifacts.

**G1 definition:** `+5` and `+15` are post-compaction/restart size observations at approximately five and fifteen minutes; they are not a growth-rate measurement.

**Causality limits:** per-key deltas localize byte changes but do not prove F04 or identify which entries grew. The ~101 s `persist_summary_rmw` event is not linked to soul-map lock wait without original telemetry. No `du` or readiness production probe is authorized by the census approval.

**Percentage accounting:** all ten compact value sizes sum to 452673 B / 53.2225%; the two largest sum to 435113 B / 51.1579%; the difference is 17560 B / 2.0646 percentage points.

**Deployment limitation:** GH workflow receipts verify the HEAD SHA used by CI/Fly workflow; they do not independently identify the image running on the census machine at the census timestamp.

**Pin correction:** the canonical SHA for the source, F02 receipt, and tracker is `e58bd17fd2b24a821c1c59a92111c4b4744f8d6a`. The `...d6c` suffix in one handoff rendering was a transcription typo, not a second revision.

**U01 artifact:** `internal/u01-builder-provider-consumer-trace.md` records the
full source blob hashes, file:line chain, exact runnable command, raw output,
exit code, conclusion, and NOT CLAIMED boundaries. The TMC/probe inputs are
deterministic injected callables; no production or external API probe was run.

**U01 independent Replit receipt:** `internal/replit-u01-verification-2026-09-28.md`
records the user-supplied independent verdict, including the exact pin, isolated
setup, the first `ModuleNotFoundError: requests` / exit `1`, corrected
successful raw receipts, clean-tree receipt, local `/api/subnets` HTTP `200`
with `75` rows, and explicit NOT CLAIMED boundaries. The first failure is a
dependency/setup failure, not a product failure. The receipt does not claim
that this run reproduced the 48-hour shrink path, the separate
seven-day-negative synthetic path, or verified production.

## F02 raw receipt

```text
PIN=e58bd17fd2b24a821c1c59a92111c4b4744f8d6a
sweep_grep_exit=0
SWEEP_EXIT=0
```

The full match list supplied with the receipt includes:

```text
internal/loop_stall_guard.py:217: os._exit(1)
internal/worker.py:89-90: signal.signal(SIGTERM/SIGINT, _handle_signal)
internal/worker.py:156: sys.exit(0)
scripts/fly_web_entrypoint.sh:28,51-55: kill/stale-worker restart handling
```

The command completed with matches; exit 0 is command success, not an empty-result assertion. Runtime environment overrides, Fly/orchestrator termination, and dynamic-library behavior remain outside this static sweep.

## F04 raw receipt

```text
PIN=e58bd17fd2b24a821c1c59a92111c4b4744f8d6a
EXIT=0
FINAL_JSON:
  adversarial_state.council_weights.a=9.0
  prediction_resolver_scheduler.cycle_generation=7
  simivision_convictions={"1":{"conviction":0.5}}
A_UPDATE_SURVIVED=True
B_CONVICTION_UPDATE_SURVIVED=False
B_RESOLVER_CYCLE_UPDATE_SURVIVED=False
B_UPDATES_LOST=True
THREAD_ERRORS=[]
git status --short: empty
```

The exact runnable Python heredoc was supplied in the F04 receipt and uses the real modules; no project files changed. This is the one recorded Cursor F04 raw receipt in the stored evidence package; no second independent raw receipt is present.
