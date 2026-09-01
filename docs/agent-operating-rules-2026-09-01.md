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

---
*Origin: V2 Saga thread, 2026-09-01. Predecessor: causal-discipline principles added to the shared roadmap 2026-08-30 (shared-chain vs. independently convergent issues, contract-level inventory sweeps). This doc supersedes and generalizes that set.*

*These rules apply to every doc in this repository that assigns agent work, proposes changes, or touches safety-critical constraints. Where a prior doc conflicts, these rules govern.*