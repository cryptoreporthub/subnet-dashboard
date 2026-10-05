---
cursor:
  subagentId: "bc-c65feb77-e459-50d4-9408-42ce96904bfa"
---

# F02 runtime-boundaries audit — scope objective

**Status:** scope document only. The audit itself is NOT started by this document.
**Repo:** cryptoreporthub/subnet-dashboard. **Workspace:** /workspace.
**Date:** 2026-10-02.

---

## 1. What F02 is

F02 is a finding from the stale-code audit (Phase 0). Its original claim was
that `os._exit(1)` in the loop stall guard is the **sole** process-termination
path in the app. The already-completed source-static sweep at the canonical pin
**refuted the "sole" qualifier**: multiple independent termination paths exist
in tracked source/config.

**Baseline pointer for reviewers.** The F02 raw receipt and pinned source
sweep baseline live in the repro registry v1.7 at
`/cursor/stores/self/internal/stale-code-repro-registry.md`
("F02 raw receipt" section). SHA-256 of that file at the time this scope was
written (2026-10-02): `07071ddde786519059eefc173cb61b118350c0a971ae1be49dc10e39ebd07d7c`
(9,473-byte registry v1.7; the same SHA is independently recorded in
`cursor-agents-communication/mission-control-log.md`). Reviewers should verify
the baseline by re-hashing this exact path and comparing; if the registry has
advanced past v1.7 by audit time, the audit must state the new version/SHA and
diff it against this pinned baseline rather than silently replacing it.

**Pin currency at doc date (2026-10-02).** The canonical audit pin
`e58bd17fd2b24a821c1c59a92111c4b4744f8d6a` is **intentionally stale relative
to main**: `origin/main` has advanced to
`ce3d820013d45577333ac8aada8c0d9e97c54129` (PR #1319 merge, 2026-10-01; the
same SHA was separately deployed to production on 2026-09-30 per the
mission-control log). The deployed SHA and the audit pin are **tracked as
separate facts**; the deployed image is never implied to equal the audit pin
or current main without verification. The audit must make an explicit
pin decision at start: either (a) re-pin to current main HEAD (full SHA,
recorded, baseline sweep re-run at the new pin), or (b) keep `e58bd17f…`
with justification plus a stated delta of termination/env-relevant changes
between the pin and main (PR #1317 and #1319 touched runtime-adjacent code).
A pin change requires re-running the F02 baseline sweep at the new pin;
staying stale requires the delta receipt.

**Completed so far (source-static scope only), at pin
`e58bd17fd2b24a821c1c59a92111c4b4744f8d6a`:**

- Pinned `git grep` direct-exit/process-termination sweep over tracked
  source/config, tests/harness excluded, `EXIT=0`.
- Matches recorded in the F02 raw receipt (registry v1.7):
  - `internal/loop_stall_guard.py:217` — `os._exit(1)`
  - `internal/worker.py:89-90` — `signal.signal(SIGTERM/SIGINT, _handle_signal)`
  - `internal/worker.py:156` — `sys.exit(0)`
  - `scripts/fly_web_entrypoint.sh:28,51-55` — `kill` / stale-worker restart
  - CI/scripts one-shot exits also matched (out of product runtime scope)
- Verdict (registry v1.7): **"VERIFIED only at source-static termination-path
  scope; runtime/environment/orchestrator boundaries remain open."**

**What remains open (this audit's target):** what actually happens at
**runtime** — which of those code paths can fire, under what conditions, with
which processes running — and how **environment variables** override that
behavior. Registry v1.7 states these exactly: "Runtime environment overrides,
Fly/orchestrator termination, and dynamic-library behavior remain outside this
static sweep."

Per the Phase 1 roadmap, F02 is unscheduled pending item-specific **Gate C**
authorization. **Gate C applies only to production probes** (production read,
runtime probe, or environment inspection beyond the existing local record); it
is not triggered by local work. **Gate C is NOT granted and NOT requested by
this document.**

### Gate A vs Gate C (disambiguation)

- **Gate A governs all local work in this audit.** Source-static sweeps and
  local runtime verification proceed under explicit Gate A controls:
  - temporary/throwaway data only, no mutation of committed state or `data/`
    contents;
  - outbound network blocked — any attempted connection fails the run;
  - no production services, production endpoints, Fly machines, or production
    credentials accessed, loaded, or printed;
  - bounded processes with explicit timeouts, deterministic inputs, explicit
    assertions.
- **Gate C is required only when a step would touch production**: production
  env inspection (e.g. `fly machine exec` env read), production log or
  artifact retrieval, health/behavior probing of the running image. None of
  the twelve questions in §2 requires Gate C as scoped here; the production env
  values question (§2 q12) is explicitly closed as NOT CLAIMED rather than
  probed.

## 2. Exact questions to answer

### 2a. Runtime-boundary questions (termination paths)

Each question is answered per pin; every answer carries file:line receipts and
an explicit claim scope. **Each question must also state at least one
falsifier** — a concrete observation that would disprove its expected answer
(e.g. "show the guard is never started at the pin", "show no env var can
disable the kill switch"). A question without a falsifier is not finished.

1. **Loop stall guard at runtime:** under what conditions does
   `internal/loop_stall_guard.py:217 os._exit(1)` actually fire? What watches
   it, what timeout/threshold triggers it, and is the guard started by default
   (server startup) or only in optional schedulers? Trace every importer/caller
   of the guard at the pin.
2. **Worker process signals:** for `internal/worker.py:89-90` and `:156`, what
   is the worker process model (who spawns it, from which entrypoint), who can
   send SIGTERM/SIGINT to it, and does the handler exit cleanly (`sys.exit(0)`)
   with cleanup?
   **Startup must be resolved from code at the pin, not from AGENTS.md prose**
   (AGENTS.md is orientation, not evidence). Trace the actual startup path:
   `internal/run_mode.py:22 background_on_web()` and
   `background_boot_allowed()`, the `server.py` boot branch that starts
   background/scheduler work (`server.py:341,358,371` and the
   `start_loop_stall_guard()` call at `server.py:279-281`), and
   `internal/worker.py:113-115`. Determine from those receipts whether the
   worker and the guard run in the default app runtime or only under
   optional/deferred modes, and which `RUN_MODE`/`BACKGROUND_ON_WEB`/
   `INLINE_WORKER`-style env values (per `fly.toml [env]`) select each mode.
3. **Entrypoint kill/restart behavior:** for
   `scripts/fly_web_entrypoint.sh:28,51-55`, under what conditions does the
   entrypoint `kill` a worker and restart it? Does this terminate the web
   process itself or only a child? What does this imply for in-flight work?
4. **Process model at the pin:** from `Procfile`, `Dockerfile`, `fly.toml`,
   and `scripts/fly_web_entrypoint.sh` at the pin, which processes run in
   production, which entrypoints spawn them, and which termination paths from
   questions 1–3 are reachable in that process model? (Static/configuration
   analysis only — no production inspection.)
   **Include supervisor/orchestrator-driven termination that is statically
   visible:** uvicorn/gunicorn worker timeouts/limits and graceful-shutdown
   settings (in `server.py`, `Dockerfile` CMD, entrypoint flags), and
   `fly.toml` restart/health-check settings (`[[http_service.checks]]` —
   `grace_period`, `interval`, `timeout` — plus `auto_stop_machines` /
   `min_machines_running`, and what a failing `/health` check causes Fly to
   do). The **kernel OOM killer on the 1GB VM** (`fly.toml [[vm]] memory =
   "1gb"`) is declared **NOT_OBSERVABLE** from static analysis: no in-VM
   observability of kernel kill decisions exists without production access,
   so this boundary is stated, not probed.
5. **(PRIORITY) Guard threshold vs legitimate long operations:** compare the
   loop stall guard's stale/threshold semantics (the `LOOP_STALL_GUARD_*`
   defaults at the pin: interval 240s, max snapshot age 5400s, max resolver
   age 21600s, 2 consecutive checks, boot grace 1500s, kill switch default
   on) against the app's own known long operations — e.g.
   `RESOLVER_CYCLE_TIMEOUT_SECONDS=360`, `LIVE_SUBNETS_SYNC_TIMEOUT_SECONDS=90`,
   `SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS=480`, the Fly health-check
   `grace_period=90s`, and any ~90s/250s/600s operation timeouts recorded in
   `fly.toml`/source. Question: can the guard's `os._exit(1)` fire **during
   legitimate, correctly-progressing work** (a slow-but-healthy cycle tripping
   the staleness/age thresholds), i.e. is any threshold mis-calibrated against
   a legitimate operation's worst-case duration? Receipts: the guard's
   staleness computation at file:line versus each long op's timeout at
   file:line. Falsifier: show for every long op that its worst-case duration
   cannot exceed the corresponding guard threshold (or identify at least one
   that can).
6. **Effects of `os._exit(1)` on in-flight work:** what is lost when the guard
   kills the process — skipped `finally` blocks, `atexit` handlers, and
   thread-pool cleanup; a kill landing mid-`write_soul_map` (or any other
   persistence write): partial/stray temp files left on the volume, and
   whether the write's `flock` is released by the OS while its data is not
   committed. Trace the write path (`_save_raw`/`write_soul_map` tmp-file +
   rename pattern) at file:line and state which debris states are statically
   provable versus which require the runtime/production boundary to remain
   NOT CLAIMED.
7. **Dynamic-library termination:** `ctypes`/foreign calls, unhandled-exception
   aborts, or C-extension exits reachable in the runtime that the grep cannot
   see. This may end as an explicit `NOT_OBSERVABLE`/`UNVERIFIED` boundary
   rather than an answer; declaring it scoped-out with justification is a
   valid answer.

### 2b. Environment-override questions

8. **Full-surface env-var inventory at the pin (Python + shell + deployment
   manifests):** enumerate every `os.environ[...]` read,
   `os.environ.get(...)`, `os.getenv(...)`, and env mutation
   (`os.environ[...] = ...`) in tracked Python source at the pin (pinned
   `git grep`, exact pattern, raw output). Exclude tests/harness/docs and
   list that exclusion explicitly.
   **Python alias mechanisms are in scope for the same question** —
   direct-access patterns alone understate the inventory. Also search for:
   `os.environ.setdefault`, `os.environ.update`, `os.environ.pop`,
   `os.putenv`/`os.unsetenv`, `del os.environ[...]`, env forwarding through
   `subprocess`/`os.spawn*` calls (`env=` kwargs, inherited environments),
   and configuration/dotenv loaders (`dotenv`, `configparser` reading env,
   custom config helpers wrapping `os.environ`). Each alias-mechanism search
   records its own exact pattern, raw output, and exit code. If an alias
   mechanism cannot be exhaustively searched statically (e.g. dynamic
   `getattr(os, name)` indirection), the residual gap is declared as
   **UNKNOWN-covered-mechanisms** in the NOT CLAIMED boundaries rather than
   silently omitted.
   **Non-Python surfaces are in the same inventory** (this is why it is a
   full-surface inventory, not a Python one): shell `$VAR`/`${VAR}` reads and
   exports in `scripts/fly_web_entrypoint.sh` (and any other tracked shell
   scripts on the runtime path), `[env]` entries in `fly.toml`, and
   `ENV`/`ARG` declarations in the `Dockerfile` — each with file:line and
   value/default. Shell-defined variables consumed by Python (e.g. entrypoint
   exports) must be reconciled with the Python inventory so no variable
   appears in only one table.
9. **Read-time classification:** for each variable, classify when it is read
   (import time vs runtime), and whether it changes termination behavior
   (guard enable/disable, timeout values, kill switches), startup, or data
   flow. Receipt: file:line per classification.
10. **Termination-relevant overrides:** which env vars can enable, disable,
   extend, or shorten any termination path from 2a (e.g. guard kill switch,
   stall timeout, worker restart thresholds)? This is the core F02
   environment question: can runtime configuration suppress or trigger the
   exits found statically?
11. **Deployment-declared env:** which variables are actually declared/set in
   `fly.toml`, `Dockerfile`, `Procfile`, and GitHub workflows at the pin
   versus which are unset-by-default with code defaults? What each code
   default is (file:line).
12. **Production env values boundary:** production's actual runtime
    environment values are **unknown and out of scope** without item-specific
    Gate C authorization. The audit must end with production env values as an
    explicit NOT CLAIMED boundary, not an inference from code defaults.

## 3. Evidence bar

The full nine-item evidence bar is in **Appendix A** so the question set stays
readable; every receipt in the audit artifacts must satisfy it in full.

## 4. Scope

### In scope

- Static source/config analysis at a pinned SHA (sweeps, call-graph traces,
  entrypoint/process-model analysis, env-var inventory and classification).
- Clean, local, non-mutating runtime verification under Gate A rules (outbound
  network blocked), only where a deterministic real-path repro adds evidence
  beyond static analysis.
- Updating the audit registry/checklist and producing Replit-facing artifacts.

### Out of scope

- **No production mutation** of any kind: no fix, deploy, restart, rollback,
  configuration change, or production write.
- **No production read or runtime probe** (env inspection, `fly` machine exec,
  health probing, log retrieval) — these require item-specific Gate C written
  authorization, which this document does NOT grant and does not request.
- **No deploy** and no merge/review-state changes on any PR.
- **No product code changes**, no dependency changes, no new PRs (evidence
  artifacts may go through an evidence-only PR only if the coordinator
  separately authorizes one, as with the F04 precedent).
- No dynamic-library/production-termination experiments; those are declared
  boundaries if not observable.
- F03/F05/F06/F07/F08 remain parked/blocked; this audit does not touch them.

## 5. Definition of "finished"

The F02 runtime-boundaries audit is **finished** when the following exist and
are internally consistent:

1. **F02 runtime audit artifact** (in `internal/` of the project store, dated
   filename) containing, for each of the twelve questions in §2: the pinned
   SHA, exact command(s), raw output, exit code, file:line receipts,
   per-question falsifier, per-question conclusion, and per-question
   NOT CLAIMED boundaries.
2. **Pinned env-var inventory table** (from question 8–11) with read-time
   classification and termination-relevance, each row backed by file:line.
3. **Updated registry/checklist entry:** the F02 row in
   `internal/stale-code-repro-registry.md` advanced from
   "source-static scope only" to a claim-scoped status (VERIFIED / PARTIAL /
   UNVERIFIED / NOT_OBSERVABLE per the roadmap status model) covering the
   runtime-boundary and environment-override scopes, with the new artifact as
   its evidence reference. A local pass closes only its declared claim; it
   must not promote production, running-image, or causality claims.
4. **Self-contained Replit handoff** (per preferences 2026-09-29/30): full
   artifact content + receipt bodies pasted or byte-preserving files attached,
   including pin, exact commands, expected raw receipts, exit codes, acceptance
   criteria, and NOT CLAIMED boundaries — never a hash-only summary, private
   path, or status packet.
5. **Gate C boundary statement:** an explicit statement of which questions,
   if any, cannot be closed without Gate C (expected: production env values,
   production termination observation) and that no Gate C request is implied
   by the audit result.

### What Replit will receive

- The F02 runtime audit artifact with all raw receipts embedded.
- The updated registry F02 row (before/after) with evidence references.
- The exact verification commands and expected outputs (raw, exit codes).
- The complete NOT CLAIMED boundary list.

### What Replit must independently verify

1. Verify the F02 baseline directly: re-hash
   `/cursor/stores/self/internal/stale-code-repro-registry.md` and compare
   against the SHA-256 recorded in §1 of this scope (`07071ddde…d7d7c`); if
   the registry advanced past v1.7, require the audit's explicit
   baseline-diff statement before reviewing further.
2. Re-run the pinned sweeps and inventory commands from a clean isolated
   checkout at the stated SHA and confirm raw outputs and exit codes match the
   artifact (setup failures reported separately, not counted as product
   failures).
3. Spot-check at least the termination-path claims (loop stall guard trigger
   chain, worker signal handlers, entrypoint kill/restart) at file:line level
   against the pin.
4. Verify the env-var inventory is complete: independently enumerate env reads
   at the pin with its own command — including at least the alias mechanisms
   and non-Python surfaces (shell, `fly.toml [env]`, `Dockerfile`) listed in
   §2 q8 — and compare tables; check any declared
   UNKNOWN-covered-mechanisms boundary is explicit, not silent.
5. Verify the claim-scoped status assigned matches the evidence and that no
   production/runtime/image/causality claim is being promoted.
6. Return raw receipts, any setup failures, hashes, and its own NOT CLAIMED
   boundaries; discrepancies go back to the audit owner rather than being
   reconciled by inference.
7. Verify every question carries a falsifier (§2) and that each falsifier is
   concrete enough that a contradicting observation would visibly break the
   stated conclusion.

**Finish is NOT:** a fix, a deploy, a closure of production behavior, or a
Gate C request. It is evidence + claim-scoped status + a verifiable handoff.

---

## Appendix A — evidence bar (per repo standards)

Every accepted receipt must include (preferences.md 2026-09-28 and Phase 1
roadmap "Evidence acceptance bar"):

- **Pinned full SHA** — the audit pin recorded in §1
  (`e58bd17fd2b24a821c1c59a92111c4b4744f8d6a` unless the pin decision re-pins
  to current main), or a newer full SHA with the pin change explicitly
  recorded and justified. Never a branch name.
- **Isolated checkout + clean-tree receipt:** `git rev-parse HEAD`, complete
  `git status --porcelain=v1 --untracked-files=all`, `git diff --quiet`,
  `git diff --cached --quiet`, plus ignored-file outputs
  (`git status --ignored --porcelain=v1 --untracked-files=all`,
  `git ls-files --others --ignored --exclude-standard`). Ignored files present
  only if listed and shown not to affect behavior.
- **Exact runnable command** for every sweep/repro — copy-pasteable, no
  paraphrase.
- **Raw output** verbatim (no summarizing, no "similar results").
- **Exit code** for every command, with the caveat recorded that grep exit 0
  means "command ran", not "assertion passed".
- **file:line receipts** for every claim about code behavior; module path +
  blob/file hashes where provenance matters (loaded-module proof if any runtime
  local repro is run, as required by the U01 precedent).
- **Real call path** for any local runtime repro: real modules, deterministic
  inputs, explicit assertions, output distinguishing pass from degraded pass.
  Outbound network blocked for local synthetic work; any attempted connection
  fails the test.
- **Explicit conclusion** per question, a **per-question falsifier** (§2
  preamble), and **explicit NOT CLAIMED boundaries** listing every neighboring
  claim not covered (production values, running image, causality,
  post-restart behavior, dynamic-library effects if unobserved, kernel OOM).
- **Setup failures reported separately** from product results (U01 precedent:
  first-run `ModuleNotFoundError` was a setup failure, not a product failure).

---

## 6. Post-scope receipts (2026-10-05)

- **PR #1317 (F04 persistence fix) merged 2026-10-01** (head `052c619`, base
  `e58bd17`). The disjoint concurrency test it was waiting for already exists on
  the main pin `ce3d8200`: `tests/test_f04_persistence.py:422`
  `test_concurrent_disjoint_setters_preserve_both_sections` (plus last-writer-wins
  tests at :368 and :394). No further PR-test action is pending on #1317.
- **SQLite implementation note (user directive, 2026-10-05):** when fixes reach
  implementation, revisit SQLite handling first. Verified `sqlite3.connect` sites
  at `e58bd17` (10 production + 1 test): `internal/chain_client.py:41,442,452,467,479`
  (VOLUME_DB_PATH), `internal/investigation/service.py:80,94,112` (CACHE_DB),
  `fetchers/_sqlite.py:28`, `message_intel/models.py:32`,
  `tests/test_message_intel_reset.py:65`. Connection lifecycle, WAL/locking, and
  multi-process behavior on the Fly data volume are the implementation-time concerns.
- **v2.7.1 reconciliation spot-checks (this chat, 2026-10-05), all at `e58bd17`:**
  confirmed — `internal/subnets/feed.py:59-61` majority gate;
  `internal/council/score_snapshots.py:157-167` monotonic stamp guard under lock;
  `server.py:3098` `_pick_netuid_from_daily_payload`; frontend daily-pick readers
  are pick-level (`pick.netuid`: `static/js/brain_letter.js:52,97`,
  `static/js/cockpit_hydrate.js:418,423,764`) with zero daily-pick-root `.netuid`
  readers (Pillar 5 retraction stands). Corrected — bare `except: pass` AST count
  at `e58bd17` is **297** across 772 `.py` files (ExceptHandler with body `[Pass]`;
  top: `internal/council/resolver.py` 17, `internal/background_boot.py` 12,
  `internal/council/resolver_scheduler.py` 10), superseding the thread's
  312/296 figures. August cancelled-jobs thread ruled OUT of scope for this chat
  by the user on 2026-10-05.