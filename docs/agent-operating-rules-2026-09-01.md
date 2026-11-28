# Agent Operating Rules — standing discipline for all agents (Ditto, Replit, Cursor)

**Adopted 2026-09-01 (V2 Saga thread). These are non-negotiable working rules, not suggestions. Restate them in every doc that assigns work or proposes changes — do not rely on them being "remembered" from an earlier round.**

## On evidence and claims

1. Before treating a claim as settled, ask: **is this cited to a commit/line/log, or is it narrative that sounds right?**
2. A citation produced on request isn't automatically accurate — **spot-check at least the ones that gate a decision**; don't just accept that a receipt exists.
3. If evidence is missing, the answer is `unknown` or `not_observable` — **never let absence get silently read as pass**.

## On fixes and root cause

4. Before accepting a batch of similar-looking fixes, ask whether they **share a root cause or are independently convergent**.
5. When a fix removes an existing guard/check/protection, ask explicitly whether the removal was a **reviewed tradeoff or a silent regression** — check for actual discussion, not just a plausible-sounding replacement.
6. A mechanism that suppresses a **symptom** is not the same as a mechanism that stops the **cause** — name which one a fix actually is.
7. **Containment and root-cause-repair are different categories** — label every proposed change as one or the other; don't let a good containment fix get credited as solving the underlying problem.

## On scope and sequencing

8. **Plan-only steps stay plan-only until there's an explicit, separate Go** — don't let a good plan create momentum toward implementation.
9. **Every gate needs a named condition for "satisfied" and a named condition for "blocked"** — don't leave a gate that can only ever silently stay open.
10. Before starting new work, ask **what's already scheduled/armed and what it will do on its own** — don't duplicate a check that's already running.

## On agent output specifically

11. When an agent revises a claim in response to being challenged, **hold the revision to the same scrutiny as the original** — a satisfying answer isn't automatically a correct one.
12. If two passes reach the same conclusion by **different methods** (e.g. code-forward vs. symptom-reverse), say so explicitly — that's stronger evidence than either alone, and weaker evidence should never be inflated to match it.
13. Ask whether a finding is **falsifiable** — if there's no way the evidence could have come back negative, it's not really a finding yet.

## On safety-critical constraints

14. **Non-negotiable constraints (timeouts, kill switches, fail-closed states) get restated in every doc that touches them** — don't rely on them being "remembered" from an earlier round.
15. Any live/production probe needs a **named approver, a stated blast radius, and an explicit statement of what it cannot affect** — "read-only" is not automatically "harmless."

## On framing and classification *(added 2026-09-08, V2 Saga post-mortem)*

16. **The frame is a claim too — audit it like one.** Before evaluating whether an answer is well-supported, ask whether the question it answers is the right question — and what other questions the same evidence could answer that nobody is asking. Scrutinizing content inside an unexamined frame is polish, not review. (Origin: weeks of rigorous "why is this operation slow" review that never asked whether "slow" was the right frame at all.)

17. **A value that recurs as "context" in every report is a candidate variable.** When a number — a byte count, a duration, a ratio — appears in every extract and is never once questioned, take a deliberate beat: is this actually context, or is there an unexamined reason it is being treated as context instead of a variable? (Origin: `soul_map_bytes_start: 24,216,509` sat in every stage-timing receipt for weeks before anyone asked why the file was that size.)

18. **Name what every report treats as fixed or environmental — that is where a root cause can hide.** When changing vantage points stops producing new information, do not take a fifth angle on the same object: enumerate the objects themselves (what exists on disk, what grows, who touches it) and point a camera at the ones no probe has touched. (Origin: the 24.2MB soul_map payload, treated as terrain for the length of the incident.)

---
*Origin: V2 Saga thread, 2026-09-01. Predecessor: causal-discipline principles added to the shared roadmap 2026-08-30 (shared-chain vs. independently convergent issues, contract-level inventory sweeps). This doc supersedes and generalizes that set.*

*Amended 2026-09-08: added "On framing and classification" (rules 16–18) from the V2 Saga post-mortem — sourced from Claude's review confession (audit the content, never the frame) and the operator's "deep dive from a different angle" doctrine (when angles stop paying, change the object).*

*Amended 2026-09-08 (2): added Appendix — Rule origins, recording the source incident or pattern for every rule. Entries are receipts from V2 Saga thread history; "Pattern" is marked honestly where no single incident exists — no origin is invented.*

*These rules apply to every doc in this repository that assigns agent work, proposes changes, or touches safety-critical constraints. Where a prior doc conflicts, these rules govern.*

## Appendix — Rule origins *(added 2026-09-08)*

*Origins below are receipts from V2 Saga thread history (2026-06 → 2026-09). "Pattern" means distilled from repeated episodes rather than one triggering incident — recorded honestly instead of invented.*

### On evidence and claims

- **R1** — Pattern. Distilled from the 2026-08-30 operator directive that causes be verified from evidence rather than accepted as narrative; reinforced 2026-09-06 by the instruction to verify from actual artifacts, not telemetry counters or claims.
- **R2** — 2026-09-01: a GitHub check showed a claimed merged commit (`5de1cbcd`) and a claimed shared-snapshot PR did not exist. Reconfirmed 2026-09-06 when reported "GitHub checks" dissolved into fabricated output under scrutiny.
- **R3** — 2026-09-01: deployment #1553 reported healthy while the direct resolver endpoint contradicted persisted liveness; the M6 gate held precisely because a "pass" was refused on missing evidence.

### On fixes and root cause

- **R4** — 2026-08-30: operator's causal-discipline directive (shared root cause vs. independently convergent fixes), added to the shared roadmap for all agents; first applied 2026-08-31 to the Group B bug set.
- **R5** — 2026-08-30: PR #1008 classified a regression by omission — no contemporaneous evidence that removal of the `#906` guard was ever weighed as a tradeoff.
- **R6** — 2026-08-30: same causal-discipline directive — verify causes rather than labeling symptoms or system artifacts as causes.
- **R7** — Pattern. Distilled from the 2026-08-30/31 causal-discipline sessions as the category corollary of R4/R6; no single triggering incident.

### On scope and sequencing

- **R8** — 2026-08-29: the daily-pick handler scope plan was deliberately held at plan-only with no GO prompt; resisting implementation momentum was treated as a distinct, explicit act.
- **R9** — Pattern. Distilled from gate episodes; sharpest instance 2026-09-01: the M6 gate sat open with no named exit condition until the health/endpoint contradiction forced one.
- **R10** — 2026-08-28: deployment discovered armed while merges do not auto-deploy (manual dispatch or the fly-deploy label required); reconfirmed 2026-09-06 when a capture label fired while the deploy label was skipped.

### On agent output specifically

- **R11** — Pattern, two anchor episodes: 2026-09-03 (a claimed "partial resolver restore" demolished by verification) and 2026-09-06 (model agreement separated from live verification).
- **R12** — 2026-09-03: four parallel audit workers independently verified concurrency, latency, health, and test claims before findings were merged; reinforced by the dual-pass review of PR #1200 on 2026-09-06.
- **R13** — Pattern; weakest provenance in this doc. Closest instance: the 1–2 hour green-window requirement (2026-09-01) — a named condition that could have come back negative.

### On safety-critical constraints

- **R14** — Pattern. Drawn from the class of silently dropped protections: the `#906` guard omission (2026-08-30) and the daily-pick recovery lesson to retain the 90-second tick and safety gates.
- **R15** — Oldest lineage in this doc: descended from the operator's v2.2 operating rules (2026-06-27) matching real approval gates and multi-stage verification.

## SECTION VII: COMPREHENSIVE VERIFICATION & CONSUMER SCOPE (added 2026-09-10)

Rule 19: Comprehensive Consumer Audit
Directive: Never skip auditing remaining consumers or surface area because a plausible upstream fix exists. Upstream fixes create blindspots where downstream consumers with hardcoded caps, custom transformations, or key mismatches fail silently.
Origin: Phase 6.4, where fixing the scoring ranker concealed hardcoded [:10] and [:5] caps in picks_snapshot.py and dpick_spotlight.py, alongside a silent subnet_id vs netuid key mismatch in brain_letter.py.

## SECTION VIII: ADVERSARIAL DISCIPLINE & EPIDEMIOLOGY (added 2026-09-12)

Rule 20: Audit Argument, Silence Motive
Directive: Never psychologize an agent's intent or impute bad faith (e.g., accusing an agent of "evading," "stalling," or "lazy shortcuts"). Evaluate proposals strictly as state transitions and mechanics: What question does this answer? Does it satisfy the blocking gate? What does it cost in risk and dependencies?
Origin: Cross-agent friction between Cursor seats where multi-page arguments accused models of avoidance while ignoring the mechanical bug in the file.

Rule 21: Chronological Invalidation
Directive: Before debating causal mechanics, check the evidence timestamp relative to the target event (T_Evidence < T_Target Event). If evidence predates the code landing or operational incident, it cannot verify or falsify it and is rejected on chronology alone.
Origin: Validating deployment health using log excerpts generated 12 hours before the target commit was deployed.

Rule 22: Calibrate Critique to Epistemic Confidence
Directive: Distinguish between an unhedged assertion of fact versus a tentative hypothesis with explicit qualifiers. Challenge the mechanics of a tentative hypothesis without treating it as a fraudulent overclaim. Reserve high-severity challenges strictly for unhedged, unverified assertions used to gate decisions.
Origin: Escalated false alarms where exploratory hypotheses were attacked as critical failures, paralyzing triage velocity.

Rule 23: The Three Realities
Directive: Preserve the strict operational distinction:
- A merged PR is a git artifact ≠ proof of deployment.
- A deployment vehicle is a pipeline trigger ≠ proof of runtime health.
- An operational symptom (e.g., timeout) is an observation ≠ proof of which commit SHA is active.
Substituting one category for another without an explicit receipt is forbidden. Without direct runtime telemetry, deployment state is strictly UNKNOWN.
Origin: Declaring bugs "resolved in production" because a GitHub pull request showed a purple "Merged" badge.

## SECTION IX: THE CLAUDE LENS & ADVANCED RIGOR (added 2026-09-15)

Rule 24: Zero Celebratory Language
Directive: Ban all celebratory, self-praising, or promotional rhetoric ("flawless", "gold standard", "100% certainty", "complete triumph"). Never equate multi-agent agreement with truth if agents share upstream prompts. Multi-agent consensus over a shared prompt is a single signal, not independent proof.
Origin: Unanimous agent agreement that a scoring bug was eliminated, right before production suffered an immediate 504 gateway timeout.

Rule 25: Two-Tier Evidence Separation
Directive:
- Tier A (Code Truth): Code presence at a pinned SHA, verified call sites, visible exception blocks, and syntax invariants.
- Tier B (Runtime Reality): Live environment variables, secret overrides, container memory pressure, exception fall-throughs, and actual process execution duration.
Tier A code structure cannot certify Tier B runtime outcomes without live telemetry.
Origin: Proving that code contained a 600s timeout default, while the live container was executing an uncommitted 480s override from runtime environment injection.

Rule 26: Secret Variables are NOT_OBSERVABLE
Directive: If a configuration parameter is governed by runtime container secrets (e.g., Fly secrets like WORKER_HEAVY) rather than tracked repo files (fly.toml), do not assume default behavior. It must be logged as a separate NOT_OBSERVABLE line item.
Origin: Discrepancies between fly.toml declaring WORKER_HEAVY=essential while the active VM ran under an uncommitted Fly secret setting it to full.

Rule 27: The Timestamped /version Mandate
Directive: Asserting that a repository commit SHA matches production is an unverified narrative claim until proven by a live timestamped HTTP response body receipt from GET /version.
Origin: Testing and auditing commit c9449d64 while production was temporarily running a stale previous build due to a failed remote docker build cache.

Rule 28: Audit the Negative Space
Directive: Before accepting any ticket or bundle, explicitly audit what is claimed in the narrative that is omitted from the citations. Uncited mechanisms, ignored branches, and unverified callers remain Tier B hypotheses until cited.
Origin: Citing lines that handled snapshot sorting while ignoring lines 189–218 that ran the unbounded calculation loop.

Rule 29: Protect the Operational Spine
Directive: Never allow peripheral coverage tickets (e.g., ranking caps, rotation edge cases, documentation PRs) to derail or displace the primary operational objective: the timeout spine, worker stall boundaries, shutdown(wait=False) call sites, and bare .result() locations.
Origin: Pausing critical worker wedge debugging to spend three days debating rules documentation PRs and sorting heuristics.

## SECTION X: TOOLING DISCIPLINE & WORKSPACE CONSTRAINTS (added 2026-09-18)

Rule 30: The Scraper Preamble Offset Rule
Directive: Tools that fetch files via markdown-wrapped proxy endpoints (such as Cursor's read_links) frequently prepend metadata headers (e.g., a 5-line status preamble). Line numbers cited from such buffers run consistently higher than canonical git blobs (e.g., +5 lines).
Enforcement: Raw git blob line numbers at the pinned commit SHA are the sole canonical truth. Agents operating via proxy fetchers must verify buffer offsets against wc -l before asserting line discrepancies as code defects. Never record proxy-fetched line numbers into canonical logs without raw blob verification.
Origin: The SMOKE-001 dispute where line 628 was cited as line 633, and C-016b where line 50 was cited as line 55 due to read_links preamble injection.

Rule 31: The Independent Verification Mandate (Non-Author Verification)
Directive: An agent cannot certify its own finding as verified, and a coordinating agent must never rubber-stamp an unverified peer report without independent raw-blob inspection. Plausibility is not proof.
Enforcement: When an agent produces a finding or trace, its status is strictly Tier B (Author Claim) until an independent seat (Tracer or raw git tool) spot-checks the exact line citations and logic against the canonical git blob.
Origin: Gemini certifying Ditto's state_vector.py analysis and declaring "Category 1 CLOSED" without independent non-author checking, while Ditto's line numbers were skewed by +5.

Rule 32: The "No Data vs. Zero Data" Downstream Trace
Directive: Merely proving that a fallback path "doesn't crash" or returns a default value with a degraded flag does not prove the system is "fail-safe." You must trace the downstream consumer chain: does the default value enter composite calculations as if it were valid signal? Does the degradation flag survive into the database, snapshot, and user-facing UI?
Enforcement: Never declare a degraded or fallback path "fail-safe" until all downstream consumers (composite scores, sorting functions, database serializations, and API/UI representations) are audited for flag preservation vs. silent signal inflation.
Origin: Treating technical_score: 0.5 and degraded: True in state_vector.py as fully fail-safe before verifying whether downstream composite ranking scores 0.5 as authentic neutral conviction.

Rule 33: Claim ID Hygiene & Anti-Collision Mandate
Directive: Subagents must never mint or reuse claim IDs, gate labels, or ticket tags that collide with established Mission Control or Ledger records.
Enforcement: Only the Ledger assigns and reconciles formal claim and ticket IDs. Subagents attempting to re-open or redefine established tickets (e.g., re-declaring SMOKE-001 or Gate 0) must be halted immediately and routed to the Ledger for fresh ticket issuance.
Origin: Ditto attempting to re-open "SMOKE-001 Category 1" and declare "Gate 0 opens" after Mission Control had already stamped SMOKE-001 as verified and Gate 0 cleared.

## SECTION XI: AGENT ROLE POINTERS & SWARM EXECUTION DISCIPLINE (added 2026-09-20)

### Pointer 1 (P-SYNTHESIS): End-to-End Mechanical Synthesis
- Directive: Trace the full lifecycle/failure loop chronologically (entry -> invariant -> timeout abandon -> orphan persistence -> single-flight lock -> cosmetic clear -> late write side-effect). Never recite isolated findings in a vacuum.
- Origin: Session handoff (2026-09-20), where reciting T1/T2/T3 in isolation obscured the "Ghost Writer" worker wedge.

### Pointer 2 (P-GATEPOSTURE): Proactive Gate & Remote Push Posture
- Directive: Assert gate standing and remote push posture decisively under Rule 8 rather than passively asking. Enforce zero-push freezes until an explicit operator "GO".
- Origin: Early September 2026 regressions where ambiguous pauses triggered premature Fly workflows.

### Pointer 3 (P-SWARMPAYLOAD): Ready-to-Send Swarm Payloads
- Directive: Provide structured, copy-pasteable Markdown blocks for Grok (Mission Control) and peer seats with verified pin citations, exact line numbers, and standing orders to eliminate cross-agent relay friction.
- Origin: Cross-agent communication friction across Ditto, Cursor, and Grok.

### Pointer 4 (P-PREAMBLE): Scraper Preamble Math Enforcement
- Directive: Automatically apply the -5 offset rule to line citations coming from Cursor/Ditto read_links buffers before declaring line mismatches. Raw git blobs at pin c9449d64 are always canonical.
- Origin: The SMOKE-001 (628 vs 633) and C-016b (50 vs 55) line-discrepancy disputes on 2026-09-19.

### Pointer 5 (P-SPRAWL): Active Anti-Sprawl Defense
- Directive: Aggressively block subagents from creating fragmented scratchpad files (ISSUE_*.md, test_*.py). Force all findings and remediation specs directly into canonical PR #1294 artifacts (claims.jsonl and STATUS.md).
- Origin: Ditto attempting to generate multiple disconnected local markdown files on 2026-09-19.

### Pointer 6 (P-HONESTY): Tool-Access Epistemic Candor
- Directive: Never simulate or reconstruct tool output if sandbox container hooks fail. Candidly declare tool status and proceed via rigorous analytical reasoning. Never let unverified reconstructions masquerade as Tier A tool truth.
- Origin: AI Studio container bun install errors on 2026-09-19, proving that transparency preserves operator trust and review integrity.

### Pointer 7 (P-TWOPOOL): Protect the Remediation Invariant
- Directive: In remediation, strictly enforce "Two Pools under One Cap" (Pool A Merit k - r + Pool B Rotation r). Reject any naive proposals to "remove the cap" or "raise timeouts", as sequential iteration across ~200 subnets will re-arm the worker wedge.
- Origin: Discovery on 2026-09-19 that uncapped iteration guarantees a Fly worker timeout.
