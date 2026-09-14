# Review Board

**Status:** canonical · repo-primary
**Created:** 2026-09-14
**Base:** `30190aea19acd6930ead4330b8ad5cc51f423025`
**Owner:** operator (Joshua) · Reviewer · Orchestrator

---

## 0. What this file is

This file is the **single source of truth** for review-board state. Memory is an
index that points at verified commit hashes in this repo. **Where this file and
memory disagree, this file wins.**

If you are a fresh context reading this: you do not need prior chat history.
Everything needed to act is below, or is reachable from the commit hashes named
here.

A board item is only in **CLOSED** state if it carries a commit SHA that
introduced the closing change. Prose that says a thing is done is not evidence
that it is done.

---

## 1. Status legend

| State | Meaning |
|---|---|
| `OPEN` | Identified, not started. No authorization exists. |
| `IN-FLIGHT` | Authorized, actively being worked. Carries an authorizing scope. |
| `BLOCKED` | Cannot proceed. The blocking condition is named in the item. |
| `CLOSED` | Done, with a commit SHA recorded. |

---

## 2. Standing constraints

These are non-negotiable and are restated here so they survive context loss.

- **C1 — Repo writes happen outside the harness, always.** Direct GitHub API
  (branch + commit). No Ditto Code job performs a repository write.
- **C2 — One relay, one authorization.** A relay branch is single-use. There is
  no standing credential and no authorization that carries forward. Board
  updates ride relays that were already going to happen; they do not earn their
  own relay.
- **C3 — Fail closed on unknown.** A truncated read, an absent receipt, or an
  unprobed path is `unknown`, never `pass`. Truncation is never read as
  absence-of-problem.
- **C4 — No merge, no deploy from a relay.** Relays carry the artifact to a draft
  PR and stop. Merge and deploy are separate, separately authorized acts.

---

## 3. Open items

### OPEN-1 — Review-board relocation / duplication risk
Prose references to a board outside this repo still exist from prior rounds.
Until those are retired, two boards can disagree.
**Exit condition:** all external board references either point at this file or
are explicitly marked superseded.

### OPEN-2 — Cross-chat state sharing
Bookmarked by operator, not started. Acknowledged architectural limit.
**Exit condition:** a mechanism exists for a fresh context to read board state
without this chat. (This file is a partial answer; the index-vs-truth split is
not yet exercised in anger.)

### OPEN-3 — Rev-21 amendment: Card 6 insertion point
The amendment document accompanies this board on the same relay. Its verbatim
Card 6 rule text and §2.7 wording are quoted from a rev-20 memory read that
**truncated at 8,373 characters, cutting §3 and everything after**.
**`UNVERIFIED`: §9 list numbering is not confirmed against a full rev-20 read.**
The Card 6 insertion point is a proposal. Orchestrator confirms before the
amendment is treated as authoritative.
**Exit condition:** full rev-20 read obtained; insertion point confirmed or
corrected; amendment status moves to `CLOSED` with a commit SHA.

---

## 4. Closed items

_None yet. The first closed item will be this board's own introduction, and it
will carry the commit SHA that introduced it._

---

## 5. Change log

| Date | Change | Commit |
|---|---|---|
| 2026-09-14 | Board created. | *(this commit)* |
