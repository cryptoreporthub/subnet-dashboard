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
