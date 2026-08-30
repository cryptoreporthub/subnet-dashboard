# Occupancy Roadmap — From Here to Done (v2 saga)

**Owner:** Joshua · **Prepared by:** Ditto · **Date:** 2026-08-30
**Repo state verified at:** #1137 open (plan-only, 5efa34c6, E1/E2 fold in flight) · #1138 open (rank 1 + rank 2 bundled, 2f480615) · #1136 open (companion docs, f8fa3905) · #1060 open (fail-closed, by design)

---

## Working principles (apply to EVERY review, every agent)

1. **Common root cause vs independent convergence.** Before accepting a batch of similar-looking fixes, ask whether they share a root cause or are independently convergent. Do not assume either; verify. (Applied: the #1008/#906/#1009/#1021/#1022 chain — four facts verified at diff level, zero assumptions.)
2. **Symptom is not a cause.** Do not list a symptom as a cause until it is verified to be a cause and not a system-level artifact. A causal claim requires receipts. Unverified claims are hypotheses, and must be labeled as such. (Applied: E2 — the exact exhausted resource is UNPROVEN until runtime capture, Patch D.)

---

## Standing constraints (invariants — never overridden by any phase)

| # | Invariant |
|---|---|
| A | **90s daily-pick timeout stays** (no KILL; observe-then-contain, never kill) |
| B | **KILL=0** — no kill/abort path is ever added |
| C | **#1112 / #1113 untouched** (no scope creep into those PRs) |
| D | **#1060 stays open, fail-closed** — closure requires a proper post-offload audit, not convenience |
| E | **#1058 stays closed** — no re-opening |
| F | **No deploy without Joshua.** Merges to main trigger the Fly CI/CD deploy → merge approval IS deploy approval. Never merge as a shortcut. |

**Gate status (locked):** Patch F **SATISFIED** with receipts · Patch D **OPEN** — gates ranks 2/3/(e), **NOT** rank 1.

---

## Phase 0 — Fold completion & lock-in (in flight now)

| Milestone | Exit criteria | Owner |
|---|---|---|
| **M0** | Cursor folds E1+E2 into #1137 per receipts (sent 08-30) | Cursor |
| **M1** | Ditto cross-verifies fold vs cursor-agents-communication/ditto-occupancy-e1e2-receipts-2026-08-30.md (f661435d); checklist → v3 | Ditto |
| **M2** | Fold approved as the **gate surface** for all rank reviews; #1136 disposition decided (merge companion docs as the landed reference, or close as superseded by #1137) | Joshua |

**Exit condition:** #1137 head reflects E1+E2 verbatim, checklist v3 signed. Phase 0 gates Phase 1.

---

## Phase 1 — Rank 1: the only mergeable cut → production

> Scope: **single-flight GET** for /api/daily-pick (rank 1). Nothing else. Everything below is about getting *this* shipped safely.

| Milestone | Exit criteria | Owner |
|---|---|---|
| **M3** | **Trim #1138 to rank-1-only.** Current head 2f480615 bundles rank 1 + rank 2 ("single-flight + 90s tick containment") — carve out everything that is not plain single-flight GET. Resulting diff must be reviewable in one sitting. If the 90s-tick portion is inseparable, spin it into its own PR gated on Patch D, don't merge it here | Cursor + Ditto review |
| **M4** | **Review vs the approved #1137 surface.** Every code line maps to a plan line; no drift, no new behavior, gates A–F untouched; B6 wording = "No deploy without Joshua" retained | Ditto |
| **M5** | **Joshua approval — merge AND deploy decision, one act.** Merging to main fires Fly CI/CD (on-push deploy). Confirm the deploy is intended and monitored, or gate the workflow first. This is the "no deploy without Joshua" gate, explicitly | Joshua |
| **M6** | **Live verification.** After deploy: GET/health latency under load, zero HOLD wedges from single-flight, daily pick publishes, pump alerts / learning loop stay healthy, no new 403/422 cascade | Ditto monitoring |

**Exit condition:** rank 1 live and green for ≥1 full daily-pick cycle (24h). This is the first *real* fix in production since the incident.

---

## Phase 2 — Runtime capture (Patch D) — unblocks ranks 2/3/(e)

> The static chain is proven (#906 removed by #1008, amplified by #1009/#1021/#1022, TMC lock convoy = leading hypothesis). **The exact exhausted resource is still unproven** — this phase proves it.

| Milestone | Exit criteria | Owner |
|---|---|---|
| **M7** | **Capture plan** — the fold's four falsifiable checks, wired into existing monitoring (/api/learning/health, watchdog, worker logs, price-cache metrics): 1) does a generation survive >90s after timeout? 2) does the retry spawn a second generation? 3) what does the abandoned worker block on (TMC lock / network / GIL / fcntl)? 4) thread-count baseline vs incident | Ditto |
| **M8** | **Capture window** — run during next incident reproduction OR controlled soak (daily-pick load + TMC contention). No manufactured overload; real traffic only | Ditto monitoring |
| **M9** | **Diagnosis** — identify the exact exhausted resource (CPU/GIL, TMC lock convoy, network waits, executor/thread capacity, file locking, or combination) and document it against the chain | Ditto (verified by Joshua) |

**Exit condition:** one of the four checks produces a falsifiable, measured answer. **Patch D → SATISFIED.** This is the hard gate before ANY of ranks 2/3/(e).

---

## Phase 3 — Ranks 2/3/(e): gated on Patch D (do not start before M9)

| Milestone | Cut | Exit criteria | Owner |
|---|---|---|---|
| **M10** | **Rank 2 — move load inside the 90s pool** (contain, don't reduce: the timed-out work is pulled into the timed pool so it can't outrun the scheduler) | Trimmed PR → review vs #1137 → approval → merge → live verify (same rigour as M3–M6) | Cursor → Ditto → Joshua |
| **M11** | **Rank 3 / (e) — generation-counter hardening** (post-timeout stale-write guard; second-gen tokens on retry) | Same gate chain as M10 | Cursor → Ditto → Joshua |
| **M12** | **Regression suite refresh** — update/replace #1008-era tests to encode intended behavior: *timeout → bounded new worker, no stale-write commits, no overlap* | Tests green on main; old skip-test semantics fully retired | Cursor |

**Exit condition:** ranks 2/3/(e) merged one at a time, each independently verified in production. No bundling across ranks — ever.

---

## Phase 4 — Close-out: proof of health, then Done

| Milestone | Exit criteria | Owner |
|---|---|---|
| **M13** | **Soak — 3 consecutive clean daily-pick cycles** post all ranks: picks publish daily, zero HOLD wedges, resolver/learning loop healthy, GET/health latency at baseline, consecutive alert failures = 0 | Ditto monitoring |
| **M14** | **Incident postmortem archive** — receipts (the E1/E2 file), diagnosis (M9), merge history, monitoring evidence consolidated into one doc in cursor-agents-communication/ (or docs/) | Ditto |
| **M15** | **Final sign-off** — Joshua reviews M13 evidence + M14 archive; checklist v-FINAL fully ticked; roadmap closed | Joshua |

---

## Definition of Done (what "finished" means)

1. **Root cause stated with receipts, not hypothesis** — Patch F code-level chain + Patch D measured resource (M9).
2. **Production is safe**: single-flight GET live (M6), no HOLD wedge, no starvation, no new 403/422 cascade, pump alerts + learning loop healthy.
3. **All three rank cuts landed**, each gated and independently verified (Phase 3).
4. **Soak green** — 3 consecutive clean cycles (M13).
5. **Standing constraints A–F all intact** — 90s timeout, KILL=0, #1112/#1113 untouched, #1060 open fail-closed, #1058 closed, no deploy without Joshua.
6. **Archive written, sign-off given** (M14/M15).

**Not part of Done (deliberately):** closing #1060, re-opening #1058, or any further scheduler redesign — those are separate decisions, made fresh after the postmortem, never tucked into this roadmap.

---

## Risk register (the three ways this stalls)

| Risk | Mitigation |
|---|---|
| **Runtime capture never reproduces** (incident may not recur in a clean system) | Capture plan A/B: passive monitoring of real traffic (checks 1/2/4) + targeted TMC contention soak (3); accept longer M8 window over manufactured load |
| **#1138 trim fights back** (rank 1 + 2 entanglement) | Don't merge rank 2 under cover; split into its own Patch-D-gated PR even if it means #1138 merges later |
| **Merge = deploy temptation** (someone merges to "just ship it") | F is non-negotiable and pre-declared; M5 makes the deploy decision explicit and visible |

---

## One-line summary

**Fold → trim → rank-1 ship → prove the resource → land 2/3/(e) → soak → archive.** Gates: Patch F closed, Patch D is the only hard lock between now and Done, and Joshua holds every merge/deploy.